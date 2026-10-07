/** Exact assignee names selected for patent research. Different legal names stay separate. */

export function addAssigneeNames(selected: string[], raw: string): string[] {
  const next = [...selected];
  for (const part of raw.split(",")) {
    const name = part.trim();
    if (!name) continue;
    const exists = next.some((item) => item.toLowerCase() === name.toLowerCase());
    if (!exists) next.push(name);
  }
  return next;
}

export function removeAssigneeName(selected: string[], name: string): string[] {
  return selected.filter((item) => item.toLowerCase() !== name.toLowerCase());
}
