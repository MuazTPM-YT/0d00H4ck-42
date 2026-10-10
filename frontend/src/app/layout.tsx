import type { Metadata, Viewport } from "next";
import { Cormorant_Garamond, Doto, IBM_Plex_Mono, Manrope } from "next/font/google";
import type { ReactNode } from "react";

import { Providers } from "@/app/providers";

import "./globals.css";

// Dither Ledger type: serif display, sans body, mono labels, dotted numerals (self-hosted at build)
const cormorant = Cormorant_Garamond({ subsets: ["latin"], weight: ["300", "400", "500", "600"], style: ["normal", "italic"], variable: "--font-cormorant", display: "swap" });
const manrope = Manrope({ subsets: ["latin"], variable: "--font-manrope", display: "swap" });
const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono", display: "swap" });
const doto = Doto({ subsets: ["latin"], weight: ["700"], variable: "--font-doto", display: "swap" });

export const metadata: Metadata = {
  title: { default: "Everest Textile Mills", template: "%s · Everest" },
  description: "Yarn to dispatch, one ledger, on the mill's own server.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

// apply the saved ink/paper choice before first paint, so the page never flashes
const THEME_BOOT = `try{if(localStorage.getItem("theme")==="dark")document.documentElement.dataset.theme="dark"}catch(e){}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en-IN" className={`${cormorant.variable} ${manrope.variable} ${plexMono.variable} ${doto.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
