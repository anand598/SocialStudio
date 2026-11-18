// Shapes of the API's JSON responses, shared by the studio's components.

export type InputType = "image" | "video" | "url";

export type Format = {
  platform: string;
  platform_label: string;
  format: string;
  label: string;
  kind: "video" | "image";
  width: number;
  height: number;
  aspect_ratio: string;
  description: string;
};

export type Config = {
  formats: Format[];
  input_types?: InputType[];
  generation_mode: "demo" | "ollama";
  max_upload_size_mb: number;
  max_video_upload_size_mb?: number;
  max_source_video_seconds?: number;
  max_music_upload_size_mb?: number;
  max_music_seconds?: number;
  max_logo_upload_size_mb?: number;
  // Days before stored media is deleted; 0 or absent means it is kept indefinitely.
  media_retention_days?: number;
};

export type Analysis = {
  product_name: string | null;
  product_category: string;
  visible_attributes: string[];
  confidence_or_limitations: string;
  facts_needing_user_confirmation: string[];
};

export type Content = {
  title?: string;
  hook: string;
  short_description: string;
  benefits: string[];
  caption: string;
  call_to_action: string;
  hashtags: string[];
  disclaimer_or_assumptions: string;
};

export type Job = {
  id: string;
  status: "queued" | "processing" | "completed" | "failed";
  stage: string;
  input_type?: InputType;
  platform?: string;
  format?: string;
  output_kind?: "video" | "image";
  has_music?: boolean;
  post_text?: string | null;
  // Set on jobs made with "Make another version"; originals are null / 1.
  parent_id?: string | null;
  variant?: number;
  // Its media was deleted after the retention period; the text is kept. Absent from older APIs.
  expired?: boolean;
  generation_mode: string;
  error_message: string | null;
  product_analysis: Analysis | null;
  generated_content: Content | null;
};

// One entry per platform, in config order (the first format of each).
export function uniquePlatforms(formats: Format[]) {
  return formats.filter(
    (item, index) =>
      formats.findIndex((other) => other.platform === item.platform) === index,
  );
}
