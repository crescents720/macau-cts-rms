import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Macau CTS Hotel RMS",
  description: "90-day hotel pricing recommendation dashboard"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-Hans">
      <body>{children}</body>
    </html>
  );
}

