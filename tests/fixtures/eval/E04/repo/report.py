def render(rows, width=12):
    lines = []
    header = "NAME".ljust(width) + "QTY".rjust(5)
    lines.append(header)
    lines.append("-" * len(header))
    total = 0
    for row in rows:
        name = str(row["name"])
        if len(name) > width:
            name = name[: width - 1] + "~"
        qty = int(row["qty"])
        if qty < 0:
            qty = 0
        total += qty
        lines.append(name.ljust(width) + str(qty).rjust(5))
    lines.append("-" * len(header))
    lines.append("TOTAL".ljust(width) + str(total).rjust(5))
    return "\n".join(lines)
