def resolve_ai_conflict(text_result: dict, visual_result: dict, igrs_rule: dict) -> dict:
    CONFIDENCE_THRESHOLD = 0.75
    VALID_RATINGS = {"SU", "7+", "13+", "17+", "PRC"}
    
    text_conf = text_result.get("confidence_score", 0)
    visual_conf = visual_result.get("confidence_score", 0)
    
    text_valid = text_conf >= CONFIDENCE_THRESHOLD
    visual_valid = visual_conf >= CONFIDENCE_THRESHOLD
    
    # GUARD 1: THE BLINDNESS CHECK
    if not text_valid and not visual_valid:
        return {
            "kategori_final": "Uncategorized", 
            "rating_final": "UNRATED", 
            "veto_applied": False,
            "reason_final": "Confidence kedua AI terlalu rendah. Butuh peninjauan manual."
        }

    dominant_modality = igrs_rule.get("dominant_modality", "EQUAL")
    
    # GUARD 2: STEALTH MODALITY
    if dominant_modality == "VISUAL" and visual_valid:
        winner = visual_result
    elif dominant_modality == "TEXT" and text_valid:
        winner = text_result
    else:
        # Berlaku kalau EQUAL, atau kalau AI yang dominan malah buta (di bawah threshold)
        if visual_conf > text_conf:
            winner = visual_result
        else:
            winner = text_result

    final_kategori = winner.get("kategori", "SAFE")
    ai_rating = winner.get("predicted_rating", "SU")
    final_reason = winner.get("reason", "Tidak ada alasan spesifik yang diberikan AI.")

    # GUARD 3: FORMAT HALLUCINATION (Pesanan Stakeholder)
    if ai_rating not in VALID_RATINGS:
        # Cuma kepake kalau AI halusinasi ngeluarin string aneh kayak "16+" atau "Dewasa"
        final_rating = igrs_rule.get("age_rating_minimal", "SU")
        print(f"[!] AI Halusinasi Format Rating ({ai_rating}). Di-fallback ke hukum IGRS: {final_rating}")
    else:
        # YES BOSS MODE: Percaya 100% sama rating AI-nya.
        final_rating = ai_rating

    return {
        "kategori_final": final_kategori,
        "rating_final": final_rating,
        "veto_applied": False, # Fitur Veto resmi dimakamkan
        "reason_final": final_reason 
    }