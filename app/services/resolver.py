def resolve_ai_conflict(text_result: dict, visual_result: dict, igrs_rule: dict) -> dict:
    CONFIDENCE_THRESHOLD = 0.60
    VALID_RATINGS = {"SU", "7+", "13+", "17+", "PRC"}
    
    text_conf = text_result.get("confidence_score", 0)
    visual_conf = visual_result.get("confidence_score", 0)
    
    text_valid = text_conf >= CONFIDENCE_THRESHOLD
    visual_valid = visual_conf >= CONFIDENCE_THRESHOLD
    
    print("\n" + "="*60)
    print(" ⚖️  PERSIDANGAN RESOLVER (ADU MEKANIK AI) ⚖️")
    print("="*60)
    print(f" [TIM 1 - TEKS]   Kategori: {text_result.get('kategori', 'SAFE'):<18} | Conf: {text_conf:.2f} | Valid: {text_valid}")
    print(f" [TIM 3 - VISUAL] Kategori: {visual_result.get('kategori', 'SAFE'):<18} | Conf: {visual_conf:.2f} | Valid: {visual_valid}")
    print("-" * 60)
    
    dominant_modality = igrs_rule.get("dominant_modality", "EQUAL")
    print(f" [HUKUM IGRS] Dominant Modality yang berlaku: {dominant_modality}")
    print("-" * 60)

    # GUARD 1: THE BLINDNESS CHECK
    if not text_valid and not visual_valid:
        print(" [VONIS] KEDUA AI BUTA (Di bawah threshold).")
        print("="*60 + "\n")
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
        alasan_menang = "Sesuai Yurisdiksi Mutlak IGRS (VISUAL)."
    elif dominant_modality == "TEXT" and text_valid:
        winner = text_result
        alasan_menang = "Sesuai Yurisdiksi Mutlak IGRS (TEXT)."
    else:
        # Berlaku kalau EQUAL, atau kalau AI yang dominan malah buta (di bawah threshold)
        if visual_conf > text_conf:
            winner = visual_result
            is_tim3_winner = True
            alasan_menang = "Adu Mekanik Murni (Confidence Visual > Teks)."
        else:
            winner = text_result
            alasan_menang = "Adu Mekanik Murni (Confidence Teks >= Visual)."

    pemenang_str = "TIM 3 (VISUAL)" if is_tim3_winner else "TIM 1 (TEKS)"
    
    print(f" [VONIS] PEMENANG: {pemenang_str}")
    print(f" [ALASAN] {alasan_menang}")
    print("="*60 + "\n")

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
        print(f" [!] AI Halusinasi Format Rating ({ai_rating}). Di-fallback ke hukum IGRS: {final_rating}\n")
    else:
        final_rating = ai_rating
        
    response["rating_final"] = final_rating

    return response