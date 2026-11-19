import type { NextConfig } from "next";

// Static export: `npm run build` writes ui/web/out, which the Vaelon core serves to the desktop app.
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  devIndicators: false,
};

export default nextConfig;
