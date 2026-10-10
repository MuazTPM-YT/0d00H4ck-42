import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Source_Serif_4 } from "next/font/google";
import type { ReactNode } from "react";

import { Providers } from "@/app/providers";

import "./globals.css";

// one industrial family: Plex Sans body and figures, Plex Mono labels and codes, Source Serif titles
// (self-hosted at build, so the running app needs no internet)
const serif = Source_Serif_4({ subsets: ["latin"], style: ["normal", "italic"], axes: ["opsz"], variable: "--font-source-serif", display: "swap" });
const plexSans = IBM_Plex_Sans({ subsets: ["latin"], variable: "--font-plex-sans", display: "swap" });
const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono", display: "swap" });

export const metadata: Metadata = {
  title: { default: "Everest Textile Mills", template: "%s · Everest" },
  description: "Yarn to dispatch, one ledger, on the mill's own server.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

// apply the saved ink/paper choice before first paint, so the page never flashes
const THEME_BOOT = `try{if(localStorage.getItem("theme")==="dark")document.documentElement.dataset.theme="dark"}catch(e){}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en-IN" className={`${serif.variable} ${plexSans.variable} ${plexMono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
