export type TrendCategory = "视觉风格" | "排版趋势" | "色彩体系" | "交互模式" | "材质纹理" | "构图手法";

export type TagCategory = "color" | "style" | "mood" | "composition" | "element" | "custom";
export type MaterialSource = "upload" | "url" | "trend";

export interface DesignTrend {
  id: string;
  name: string;
  name_en: string;
  category: TrendCategory;
  description: string;
  keywords: string[];
  color_palette: string[];
  mood_keywords: string[];
  source_urls: string[];
  difficulty: 1 | 2 | 3;
  example_prompt: string;
  fetched_at?: string | null;
  summary_mode?: "llm" | "heuristic" | null;
  source_count?: number | null;
  source_labels?: string[] | null;
  published_at?: string | null;
}

export interface DailyTrendRoll {
  date: string;
  trend: DesignTrend;
  dice_face: number;
  dice_category: TrendCategory;
  pool: DesignTrend[];
  pool_fetched_at?: string | null;
}

export interface TrendHistoryRecord {
  date: string;
  trend: DesignTrend;
  dice_face: number;
  dice_category: TrendCategory;
}

export interface MaterialTag {
  name: string;
  type: "auto" | "manual";
  confidence?: number | null;
  category: TagCategory;
}

export interface MaterialItem {
  id: string;
  user_id: string;
  filename: string;
  original_url?: string | null;
  thumbnail_url: string;
  full_url: string;
  width: number;
  height: number;
  file_size: number;
  mime_type: string;
  tags: MaterialTag[];
  colors: string[];
  created_at?: string | null;
  updated_at?: string | null;
  source: MaterialSource;
  trend_id?: string | null;
}

export interface MaterialList {
  items: MaterialItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface UpdateMaterialTagsPayload {
  add: MaterialTag[];
  remove: string[];
}

export interface NetworkNode {
  id: string;
  label: string;
  thumbnail: string;
  tags: string[];
  colors: string[];
  group: number;
  source: MaterialSource;
}

export interface NetworkLink {
  source: string;
  target: string;
  weight: number;
  shared_tags: string[];
  shared_category?: string | null;
}

export interface NetworkData {
  nodes: NetworkNode[];
  links: NetworkLink[];
}

export const TREND_CATEGORY_ORDER: TrendCategory[] = ["视觉风格", "排版趋势", "色彩体系", "交互模式", "材质纹理", "构图手法"];

export const TREND_FACE_LABELS: Record<number, TrendCategory> = {
  1: "视觉风格",
  2: "排版趋势",
  3: "色彩体系",
  4: "交互模式",
  5: "材质纹理",
  6: "构图手法",
};

export const TREND_CATEGORY_TINTS: Record<TrendCategory, string> = {
  "视觉风格": "rgba(37,99,235,0.10)",
  "排版趋势": "rgba(15,23,42,0.08)",
  "色彩体系": "rgba(217,119,6,0.12)",
  "交互模式": "rgba(14,165,233,0.12)",
  "材质纹理": "rgba(124,58,237,0.12)",
  "构图手法": "rgba(71,85,105,0.10)",
};

export const TREND_CATEGORY_ACCENTS: Record<TrendCategory, string> = {
  "视觉风格": "#2563EB",
  "排版趋势": "#0F172A",
  "色彩体系": "#D97706",
  "交互模式": "#0EA5E9",
  "材质纹理": "#7C3AED",
  "构图手法": "#475569",
};
