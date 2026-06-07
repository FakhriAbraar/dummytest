def resolve_ai_conflict(text_result: dict, visual_result: dict, igrs_rule: dict) -> dict:
    CONFIDENCE_THRESHOLD = 0.60
    VALID_RATINGS = {"SU", "7+", "13+", "17+", "PRC"}
    
    text_conf = text_result.get("confidence_score", 0)
    visual_conf = visual_result.get("confidence_score", 0)
    
    text_valid = text_conf >= CONFIDENCE_THRESHOLD
    visual_valid = visual_conf >= CONFIDENCE_THRESHOLD
    
    print(f"[resolver] conflict resolution (confidence_threshold={CONFIDENCE_THRESHOLD})")
    print(f"[resolver] tim1(text)   kategori={text_result.get('kategori', 'SAFE')} conf={text_conf:.2f} valid={text_valid}")
    print(f"[resolver] tim3(visual) kategori={visual_result.get('kategori', 'SAFE')} conf={visual_conf:.2f} valid={visual_valid}")

    dominant_modality = igrs_rule.get("dominant_modality", "EQUAL")
    print(f"[resolver] igrs dominant_modality={dominant_modality}")

    # GUARD 1: kedua confidence di bawah threshold -> tidak bisa diputuskan.
    if not text_valid and not visual_valid:
        print("[resolver] result=UNRATED (both confidences below threshold)")
        return {
            "kategori_final": "UNRATED", 
            "veto_applied": False,
            "reason_final": "Confidence kedua AI terlalu rendah. Butuh peninjauan manual."
        }
    
    # GUARD 2: STEALTH MODALITY & WINNER TRACKING
    is_tim3_winner = False
    alasan_menang = ""
    
    if dominant_modality == "VISUAL" and visual_valid:
        winner = visual_result
        is_tim3_winner = True
        alasan_menang = "igrs dominant_modality=VISUAL"
    elif dominant_modality == "TEXT" and text_valid:
        winner = text_result
        alasan_menang = "igrs dominant_modality=TEXT"
    else:
        # EQUAL, atau modality dominan di bawah threshold -> pilih confidence tertinggi.
        if visual_conf > text_conf:
            winner = visual_result
            is_tim3_winner = True
            alasan_menang = "highest confidence (visual > text)"
        else:
            winner = text_result
            alasan_menang = "highest confidence (text >= visual)"

    pemenang_str = "tim3(visual)" if is_tim3_winner else "tim1(text)"

    print(f"[resolver] winner={pemenang_str} reason={alasan_menang}")

    final_kategori = winner.get("kategori", "SAFE")
    final_reason = winner.get("reason", "Tidak ada alasan spesifik yang diberikan AI.")

    response = {
        "kategori_final": final_kategori,
        "veto_applied": False, 
        "reason_final": final_reason 
    }

    ai_rating = winner.get("predicted_rating", "SU")
    
    if ai_rating not in VALID_RATINGS:
        final_rating = igrs_rule.get("age_rating_minimal", "SU")
        print(f"[resolver] invalid rating from AI ({ai_rating}), fallback to igrs minimal={final_rating}")
    else:
        final_rating = ai_rating
        
    response["rating_final"] = final_rating

    return response