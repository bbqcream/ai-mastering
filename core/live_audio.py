"""Capture Live through the system loopback, restoring temporary transport/solo state."""

import asyncio
import threading
import time
import warnings

import numpy as np

from .live_safety import CaptureOverload


class LoopbackRecorder:
    def __init__(self, device=None, sample_rate=48000):
        self.device = device
        self.sample_rate = sample_rate
        self.ready = threading.Event()
        self.stop = threading.Event()
        self.peak = 0.0

    def record(self, max_seconds):
        import soundcard as sc
        from soundcard.mediafoundation import SoundcardRuntimeWarning

        chunks = []
        microphone = sc.get_microphone(self.device or sc.default_speaker().id, include_loopback=True)
        with microphone.recorder(samplerate=self.sample_rate, channels=2, blocksize=8192) as recorder:
            self.ready.set()
            start = time.monotonic()
            while not self.stop.is_set() and time.monotonic() - start < max_seconds:
                with warnings.catch_warnings(record=True) as observed:
                    warnings.simplefilter("always", SoundcardRuntimeWarning)
                    chunk = recorder.record(numframes=8192)
                if any(issubclass(item.category, SoundcardRuntimeWarning) and
                       str(item.message) == "data discontinuity in recording" for item in observed):
                    raise CaptureDiscontinuity(
                        "WASAPI reported a data discontinuity; this capture was discarded"
                    )
                if not np.isfinite(chunk).all():
                    raise RuntimeError("오디오 캡처에 유효하지 않은 샘플이 있습니다")
                self.peak = max(self.peak, float(np.max(np.abs(chunk))))
                chunks.append(chunk)
        if not chunks:
            raise RuntimeError("루프백 오디오를 캡처하지 못했습니다")
        return np.concatenate(chunks).astype(np.float32), self.sample_rate


class CaptureDiscontinuity(RuntimeError):
    """A loopback buffer gap invalidated the current audio capture."""


async def capture(session, call, start_beats, end_beats, track_index=None, device=None, max_seconds=900):
    if end_beats <= start_beats:
        raise ValueError("캡처 종료 위치는 시작 위치보다 커야 합니다")
    transport = await call(session, "get_session_info")
    if transport.get("loop"):
        raise RuntimeError("Live Arrangement Loop를 꺼야 전체 구간을 캡처할 수 있습니다")
    states = []
    if track_index is not None:
        for index in range(transport["track_count"]):
            mixer = await call(session, "get_mixer", track_index=index)
            # Group tracks do not expose a readable Arm state through this
            # Remote Script's get_track_info implementation. They are not
            # solo targets here, so exclude them before requesting track info.
            if mixer.get("is_group"):
                continue
            info = await call(session, "get_track_info", track_index=index)
            states.append((index, info["name"], bool(info["solo"])))
    recorder = LoopbackRecorder(device)
    recording = None
    overloaded = False
    try:
        await call(session, "stop_playback")
        for index, _, _ in states:
            await call(session, "set_track_solo", track_index=index, solo=index == track_index)
        recording = asyncio.create_task(asyncio.to_thread(recorder.record, max_seconds + 10))
        while not recorder.ready.is_set():
            if recording.done():
                await recording
            await asyncio.sleep(0.05)
        await call(session, "start_playback")
        # Live resets its playhead when playback starts. Seek after starting,
        # while transport is running, so captures begin at the requested beat.
        await call(session, "set_arrangement_time", time=start_beats)
        deadline = time.monotonic() + max_seconds
        playback_started = time.monotonic()
        previous = start_beats
        last_move = time.monotonic()
        while True:
            if recording.done():
                # A discontinuity can stop the recorder thread before Live
                # reaches the requested end position. Surface it immediately
                # so the temporary Solo state can be restored and retried.
                await recording
                raise RuntimeError("Loopback recorder stopped before the capture ended")
            if getattr(recorder, "peak", 0) >= 0.98:
                overloaded = True
                raise CaptureOverload("루프백 피크가 -0.18 dBFS에 도달해 재생을 중단했습니다")
            info = await call(session, "get_session_info")
            position = info["current_song_time"]
            if position >= end_beats:
                break
            if position < previous - 0.5:
                # Live can report the pre-seek position for a short moment
                # after transport starts. Ignore only this startup race.
                if time.monotonic() - playback_started > 2.0:
                    raise RuntimeError(f"캡처 중 재생 위치가 되돌아갔습니다 ({previous:.2f} -> {position:.2f} beats)")
                await asyncio.sleep(0.2)
                continue
            if position > previous:
                last_move = time.monotonic()
            if time.monotonic() > deadline or time.monotonic() - last_move > 10:
                raise RuntimeError("캡처 제한 시간 초과 또는 Live 재생이 멈췄습니다")
            previous = position
            await asyncio.sleep(0.2)
        await call(session, "stop_playback")
        await asyncio.sleep(2)  # Capture effect tails.
        if getattr(recorder, "peak", 0) >= 0.98:
            overloaded = True
            raise CaptureOverload("이펙트 테일에서 출력 과부하를 감지했습니다")
    finally:
        recorder.stop.set()
        restore_errors = []
        try:
            if recording is not None:
                audio = await recording
        finally:
            # Track indices can shift while Live changes views or updates its
            # track list. Verify the saved index first, then resolve by name;
            # never apply a saved Solo value to a different track.
            current_tracks = {}
            try:
                current_info = await call(session, "get_session_info")
                for current_index in range(current_info["track_count"]):
                    mixer = await call(session, "get_mixer", track_index=current_index)
                    if not mixer.get("is_group"):
                        info = await call(session, "get_track_info", track_index=current_index)
                        current_tracks.setdefault(info["name"], []).append(current_index)
            except Exception as exc:
                restore_errors.append(f"트랙 목록 확인 실패: {exc}")
            for index, name, solo in states:
                try:
                    try:
                        current = await call(session, "get_track_info", track_index=index)
                    except Exception:
                        current = None
                    if current is not None and current.get("name") == name:
                        restore_index = index
                    else:
                        matches = current_tracks.get(name, [])
                        if len(matches) == 1:
                            restore_index = matches[0]
                        else:
                            raise RuntimeError(f"트랙 '{name}' 복구 대상을 유일하게 찾지 못함")
                    await call(session, "set_track_solo", track_index=restore_index, solo=solo)
                except Exception as exc:
                    restore_errors.append(str(exc))
            for tool, params in [
                ("stop_playback", {}),
                ("set_arrangement_time", {"time": transport["current_song_time"]}),
                ("start_playback" if transport["is_playing"] and not overloaded else "stop_playback", {}),
            ]:
                try:
                    await call(session, tool, **params)
                except Exception as exc:
                    restore_errors.append(str(exc))
            if restore_errors:
                raise RuntimeError("Live 임시 상태 복구 확인 필요: " + ", ".join(restore_errors))
    return audio
