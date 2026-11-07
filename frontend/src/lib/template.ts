/**
 * Template utilities for {{variable}} highlighting and rendering.
 */

/**
 * Replace {{variable}} placeholders in a template string with actual values.
 */
export function renderTemplate(template: string, values: Record<string, string>): string {
  return template.replace(/\{\{([^}]+)\}\}/g, (_match, key) => {
    const trimmed = key.trim();
    return values[trimmed] !== undefined ? values[trimmed] : `{{${trimmed}}}`;
  });
}

/**
 * Split a template string into segments for syntax highlighting.
 * Returns segments of type "text" or "variable".
 */
export function templateSegments(template: string): { type: "text" | "variable"; value: string }[] {
  const segments: { type: "text" | "variable"; value: string }[] = [];
  const regex = /\{\{([^}]+)\}\}/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(template)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: "text", value: template.slice(lastIndex, match.index) });
    }
    segments.push({ type: "variable", value: match[1].trim() });
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < template.length) {
    segments.push({ type: "text", value: template.slice(lastIndex) });
  }

  return segments;
}

/**
 * Extract all variable names from a template string.
 */
export function extractVariables(template: string): string[] {
  const vars: string[] = [];
  const regex = /\{\{([^}]+)\}\}/g;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(template)) !== null) {
    vars.push(match[1].trim());
  }
  return vars;
}