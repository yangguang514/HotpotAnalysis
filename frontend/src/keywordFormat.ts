import type { KeywordGroup } from "./types";

export interface ParsedKeywords {
  groups: KeywordGroup[];
  global_filters: string[];
}

export function keywordsToText(keywords: ParsedKeywords): string {
  const sections: string[] = [];
  const globalFilters = keywords.global_filters.filter((line) => line.trim());
  if (globalFilters.length) {
    sections.push(`[GLOBAL_FILTER]\n${globalFilters.join("\n")}`);
  }

  const hasWordGroups = keywords.groups.some((group) => group.lines.some((line) => line.trim()));
  if (globalFilters.length && hasWordGroups) sections.push("[WORD_GROUPS]");

  for (const group of keywords.groups) {
    const lines = group.lines.filter((line) => line.trim());
    if (!lines.length) continue;

    const name = group.display_name.trim();
    const firstLine = lines[0];
    if (name && !/\s=>\s/.test(firstLine) && !/^\[.+\]$/.test(firstLine)) {
      lines.unshift(`[${name}]`);
    }
    sections.push(lines.join("\n"));
  }

  return `${sections.join("\n\n")}\n`;
}

export function textToKeywords(text: string): ParsedKeywords {
  const groups: KeywordGroup[] = [];
  const globalFilters: string[] = [];
  let section: "WORD_GROUPS" | "GLOBAL_FILTER" = "WORD_GROUPS";

  for (const block of text.split(/\n\s*\n/).map((part) => part.trim()).filter(Boolean)) {
    const lines = block
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#"));
    if (!lines.length) continue;

    if (/^\[GLOBAL_FILTER\]$/i.test(lines[0])) {
      section = "GLOBAL_FILTER";
      lines.shift();
    } else if (/^\[WORD_GROUPS\]$/i.test(lines[0])) {
      section = "WORD_GROUPS";
      lines.shift();
    }
    if (!lines.length) continue;

    if (section === "GLOBAL_FILTER") {
      globalFilters.push(...lines);
      continue;
    }

    let displayName = "";
    let body = lines;
    if (/^\[.+\]$/.test(lines[0])) {
      displayName = lines[0].slice(1, -1);
      body = lines.slice(1);
    } else if (lines[0].includes("=>")) {
      displayName = lines[0].split("=>")[1].trim();
    }
    if (body.length) {
      groups.push({ display_name: displayName || body[0], lines: body });
    }
  }

  return { groups, global_filters: globalFilters };
}
