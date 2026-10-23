def check_answer(ipt, ans):
    # Preserve legacy matching (including slash-separated alternatives).
    return ipt.strip().lower() in ans.strip().lower().split('/')
