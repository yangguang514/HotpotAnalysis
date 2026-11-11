import { describe, expect, it } from "vitest";
import { keywordsToText, textToKeywords } from "./keywordFormat";

describe("keyword text conversion", () => {
  it("preserves global filters and groups across a raw-editor round trip", () => {
    const keywords = {
      global_filters: ["震惊", "/营销|广告/"],
      groups: [
        {
          display_name: "大熊猫",
          lines: ["/大熊猫|熊猫/ => 大熊猫"],
        },
        {
          display_name: "生态",
          lines: ["/生态|环境保护/"],
        },
      ],
    };

    expect(textToKeywords(keywordsToText(keywords))).toEqual(keywords);
  });
});
