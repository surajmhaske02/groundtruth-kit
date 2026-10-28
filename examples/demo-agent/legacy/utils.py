def parse_output(raw):
    return raw.get("answer", "")


def format_answer_v2(rows, q):
    out = []
    for r in rows:
        if isinstance(r, dict):
            t = r.get("text", "")
            out.append("- " + t.strip())
        else:
            out.append("- " + str(r))
    head = "Answer to: " + q
    return head + "\n" + "\n".join(out)
