export interface KeywordGroup {
  display_name: string;
  lines: string[];
}

export interface PlatformConfig {
  id: string;
  name: string;
  domain: string;
  enabled?: boolean;
}

export interface WebConfig {
  version: number;
  keywords: {
    groups: KeywordGroup[];
    global_filters: string[];
  };
  platforms: PlatformConfig[];
  api_url: string;
  schedule: {
    enabled: boolean;
    weekdays: number[];
    times: string[];
    timezone: string;
  };
  report: {
    mode: string;
    range_days: number;
    sort_by_position_first: boolean;
    max_news_per_keyword: number;
    rank_threshold: number;
  };
}

export interface PlatformCatalogItem {
  id: string;
  name: string;
}

export interface PlatformCatalogResponse {
  catalog: PlatformCatalogItem[];
  domains: Record<string, string>;
}

export interface CrawlStats {
  platforms_total: number;
  platforms_success: number;
  platforms_failed: string[];
  new_titles: number;
  duration_seconds: number;
}

export interface StatusResponse {
  backend: "kv" | "file" | "memory" | string;
  persistent: boolean;
  schedule: {
    enabled: boolean;
    times: string[];
    weekdays: number[];
    timezone: string;
  };
  last_crawl: {
    time: string | null;
    date: string | null;
    status: string | null;
    stats: CrawlStats | null;
  };
}

export interface ReportNewsItem {
  title: string;
  url: string;
  platform: string;
  count: number;
  ranks: number[];
  first_time: string;
  last_time: string;
}

export interface ReportGroup {
  name: string;
  count: number;
  news: ReportNewsItem[];
}

export interface WebReport {
  range: {
    days: number;
  };
  total_news: number;
  total_matched: number;
  groups: ReportGroup[];
}

export type TabId = "keywords" | "schedule" | "report";
