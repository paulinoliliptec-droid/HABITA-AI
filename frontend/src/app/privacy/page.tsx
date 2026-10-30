import type { Metadata } from "next";
import { PrivacyContent } from "./PrivacyContent";

export const metadata: Metadata = { title: "Privacy & terms" };

export default function PrivacyPage() {
  return <PrivacyContent />;
}
