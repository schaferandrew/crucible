import type { Metadata } from "next";
import type { ReactNode } from "react";
import Layout from "../components/Layout";
import "../styles/globals.css";

export const metadata: Metadata = {
  title: { default: "Lantern Books", template: "%s | Lantern Books" },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Layout>{children}</Layout>
      </body>
    </html>
  );
}
