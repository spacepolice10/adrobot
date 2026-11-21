function moveSuggestionFocus(event, direction) {
  const suggestions = Array.from(
    event.currentTarget.querySelectorAll(".form-suggestions > li > button"),
  );
  if (!suggestions.length) return;

  event.preventDefault();
  const current = suggestions.indexOf(event.target);
  const next = current === -1
    ? (direction > 0 ? 0 : suggestions.length - 1)
    : (current + direction + suggestions.length) % suggestions.length;
  suggestions[next].focus();
}
