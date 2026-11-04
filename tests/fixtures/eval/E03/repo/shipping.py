def fee(weight_g):
    if weight_g < 500:
        return 300
    if weight_g < 1000:
        return 500
    if weight_g < 2000:
        return 800
    return 800 + (weight_g - 2000) // 1000 * 100
