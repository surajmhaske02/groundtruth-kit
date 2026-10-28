def parse_output(raw):
    if "answer" in raw:
        return raw["answer"]
    return raw


def format_answer(results, question):
    lines = []
    for item in results:
        if isinstance(item, dict):
            text = item.get("text", "")
            lines.append("- " + text.strip())
        else:
            lines.append("- " + str(item))
    header = "Answer to: " + question
    return header + "\n" + "\n".join(lines)
