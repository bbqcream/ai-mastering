"""Keep local-model context focused while retaining full receipts in the report."""

from .mix_review import masking_context


def analysis_summary(analysis):
    return {key: analysis[key] for key in (
        "silent", "lufs", "true_peak_db", "crest_db", "bands_db", "full_scale_fraction",
        "stereo_correlation", "side_to_mid_db", "dc_offset", "sections",
    ) if key in analysis}


def model_context(tracks, info, catalog, observations, revision, measured):
    focus_index = next(iter(tracks))
    for event in reversed(observations):
        if event.get("arguments", {}).get("track_index") in tracks:
            focus_index = event["arguments"]["track_index"]
            break
    focus = tracks[focus_index]
    history = []
    current_device = None
    for event in observations[-8:]:
        item = {key: event[key] for key in ("tool", "arguments", "error", "revision") if key in event}
        result = event.get("result")
        if isinstance(result, dict) and "review" in result:
            review = result["review"]
            item["review"] = {"accepted": review["accepted"], "reasons": review["reasons"],
                              "before": analysis_summary(review["before"]), "after": analysis_summary(review["after"])}
        device_result = result.get("readback", result) if isinstance(result, dict) else None
        if isinstance(device_result, dict) and "device" in device_result:
            current_device = {"track_index": event["arguments"].get("track_index"),
                              "device_index": event["arguments"].get("device_index"), "result": device_result}
            item["device_name"] = device_result["device"]["name"]
        elif event.get("tool") == "measure_audio" and isinstance(result, dict):
            item["result"] = analysis_summary(result)
        elif event.get("tool") == "prepare_track" and isinstance(result, list):
            item["result"] = [{key: entry[key] for key in ("effect", "available", "loaded", "device_index") if key in entry} for entry in result]
        elif event.get("tool") == "get_track_info" and isinstance(result, dict):
            item["result"] = {key: result[key] for key in ("name", "index", "devices", "mute", "solo") if key in result}
        elif not item.get("review"):
            item["result"] = result[:6000] if isinstance(result, str) else result
        history.append(item)
    return {
        "tracks": {index: {"name": track["track"]["name"], "role": track["role"],
                           "lufs": track["analysis"].get("lufs"), "peak_db": track["analysis"].get("true_peak_db"),
                           "volume_db": track["mixer"]["volume"].get("db"),
                           "needs_measurement": measured.get(index) != revision} for index, track in tracks.items()},
        "focus_track": {"track_index": focus_index,
                        "track": {key: focus["track"][key] for key in ("name", "index", "devices", "mute", "solo") if key in focus["track"]},
                        "mixer": {key: focus["mixer"][key] for key in ("name", "volume", "panning") if key in focus["mixer"]},
                        "role": focus["role"], "analysis": analysis_summary(focus["analysis"]),
                        "mixing_guidance": focus["mixing_guidance"]},
        "session": info, "tools": catalog, "history": history, "current_device": current_device,
        "revision": revision, "measurements_at_revision": {str(key): value for key, value in measured.items()},
        "potential_masking": masking_context([
            {"name": track["track"]["name"], "role": track["role"], "analysis": track["analysis"]}
            for track in tracks.values()
        ])[:16],
    }
