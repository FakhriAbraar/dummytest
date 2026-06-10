def resolve_ai_conflict(text_result: dict, visual_result: dict, igrs_rule: dict) -> dict:
    VALID_RATINGS = {"SU", "7+", "13+", "17+", "PRC"}
    RATING_SEVERITY = {"SU": 0, "7+": 1, "13+": 2, "17+": 3, "PRC": 4, "UNRATED": -1}
    
    text_rating = text_result.get("predicted_rating", "SU")
    if text_rating not in VALID_RATINGS: 
        text_rating = "SU"
        
    visual_rating = visual_result.get("predicted_rating", "SU")
    if visual_rating not in VALID_RATINGS: 
        visual_rating = "SU"
        
    text_sev = RATING_SEVERITY.get(text_rating, 0)
    visual_sev = RATING_SEVERITY.get(visual_rating, 0)
    
    print(f"[resolver] worst-case logic resolution")
    print(f"[resolver] tim1(text)   kategori={text_result.get('kategori', 'SAFE')} rating={text_rating} sev={text_sev}")
    print(f"[resolver] tim3(visual) kategori={visual_result.get('kategori', 'SAFE')} rating={visual_rating} sev={visual_sev}")

    if visual_sev > text_sev:
        winner = visual_result
        final_rating = visual_rating
        alasan = "visual severity > text severity"
    elif text_sev > visual_sev:
        winner = text_result
        final_rating = text_rating
        alasan = "text severity > visual severity"
    else:
        # Equal severity
        if visual_result.get("kategori", "SAFE") != "SAFE":
            winner = visual_result
            final_rating = visual_rating
            alasan = "equal severity, visual is specific category"
        else:
            winner = text_result
            final_rating = text_rating
            alasan = "equal severity, text prioritized or both SAFE"

    print(f"[resolver] winner chosen reason={alasan}")

    response = {
        "kategori_final": winner.get("kategori", "SAFE"),
        "veto_applied": False, 
        "reason_final": winner.get("reason", "Tidak ada alasan spesifik yang diberikan AI."),
        "rating_final": final_rating
    }

    return response