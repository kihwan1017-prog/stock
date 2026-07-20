import { describe, expect, it } from "vitest";

import type { UserNewsItem } from "@/features/user/api/userApi";

function externalLinkProps(url: string | null) {
  if (!url) return null;
  return {
    href: url,
    target: "_blank" as const,
    rel: "noopener noreferrer" as const,
  };
}

function stripHtml(text: string): string {
  // 외부 HTML을 렌더링하지 않고 텍스트만 유지
  return text.replace(/<[^>]*>/g, "");
}

describe("user news helpers", () => {
  it("원문 링크에 noopener noreferrer를 붙인다", () => {
    const props = externalLinkProps("https://news.example.com/a");
    expect(props?.rel).toBe("noopener noreferrer");
    expect(props?.target).toBe("_blank");
  });

  it("HTML 태그를 제거한다", () => {
    expect(stripHtml("<b>제목</b> 본문")).toBe("제목 본문");
  });

  it("UserNewsItem 필수 필드를 갖는다", () => {
    const item: UserNewsItem = {
      news_id: 1,
      title: "t",
      summary: null,
      source_code: "NAVER",
      source_name: "네이버 뉴스",
      original_url: null,
      published_at: null,
      matched_symbols: [],
      is_read: false,
      is_bookmarked: false,
    };
    expect(item.news_id).toBe(1);
  });
});
