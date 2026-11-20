"""Capture Live through the system loopback, restoring temporary transport/solo state."""

import asyncio
import threading
import time

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

        chunks = []
        microphone = sc.get_microphone(self.device or sc.default_speaker().id, include_loopback=True)
        with microphone.recorder(samplerate=self.sample_rate, channels=2, blocksize=2048) as recorder:
            self.ready.set()
            start = time.monotonic()
            while not self.stop.is_set() and time.monotonic() - start < max_seconds:
                chunk = recorder.record(numframes=2048)
                if not np.isfinite(chunk).all():
                    raise RuntimeError("오디오 캡처에 유효하지 않은 샘플이 있습니다")
                self.peak = max(self.peak, float(np.max(np.abs(chunk))))
                chunks.append(chunk)
        if not chunks:
            raise RuntimeError("루프백 오디오를 캡처하지 못했습니다")
        return np.concatenate(chunks).astype(np.float32), self.sample_rate


async def capture(session, call, start_beats, end_beats, track_index=None, device=None, max_seconds=900):
    if end_beats <= start_beats:
        raise ValueError("캡처 종료 위치는 시작 위치보다 커야 합니다")
    transport = await call(session, "get_session_info")
    if transport.get("loop"):
        raise RuntimeError("Live Arrangement Loop를 꺼야 전체 구간을 캡처할 수 있습니다")
    states = []
    if track_index is not None:
        for index in range(transport["track_count"]):
            info = await call(session, "get_track_info", track_index=index)
            states.append((index, info["name"], bool(info["solo"])))
    recorder = LoopbackRecorder(device)
    recording = None
    overloaded = False
    try:
        await call(session, "stop_playback")
        for index, _, _ in states:
            await call(session, "set_track_solo", track_index=index, solo=index == track_index)
        await call(session, "set_arrangement_time", time=start_beats)
        recording = asyncio.create_task(asyncio.to_thread(recorder.record, max_seconds + 10))
        while not recorder.ready.is_set():
            if recording.done():
                await recording
            await asyncio.sleep(0.05)
        await call(session, "start_playback")
        deadline = time.monotonic() + max_seconds
        previous = start_beats
        last_move = time.monotonic()
        while True:
            if getattr(recorder, "peak", 0) >= 0.98:
                overloaded = True
                raise CaptureOverload("루프백 피크가 -0.18 dBFS에 도달해 재생을 중단했습니다")
            info = await call(session, "get_session_info")
            position = info["current_song_time"]
            if position >= end_beats:
                break
            if position < previous - 0.5:
                raise RuntimeError("캡처 중 재생 위치가 되돌아갔습니다")
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
            for index, name, solo in states:
                try:
                    current = await call(session, "get_track_info", track_index=index)
                    if current["name"] != name:
                        raise RuntimeError("캡처 중 트랙 순서 변경")
                    await call(session, "set_track_solo", track_index=index, solo=solo)
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
