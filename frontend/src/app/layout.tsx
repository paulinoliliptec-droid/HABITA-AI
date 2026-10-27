import type { Metadata, Viewport } from "next";
import { Instrument_Sans, Source_Serif_4 } from "next/font/google";
import { TopBar } from "@/components/shell/TopBar";
import "./globals.css";

const sans = Instrument_Sans({
  variable: "--font-sans-loaded",
  subsets: ["latin", "latin-ext"],
  display: "swap",
});

const serif = Source_Serif_4({
  variable: "--font-serif-loaded",
  subsets: ["latin", "latin-ext"],
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "HABITA AI",
    template: "%s · HABITA AI",
  },
  description: "Global Property Intelligence & Permitting OS",
};

export const viewport: Viewport = {
  themeColor: "#f6f5f1",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${sans.variable} ${serif.variable}`}>
      <body>
        <TopBar />
        {children}
      </body>
    </html>
  );
}
