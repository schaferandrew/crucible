import Link from "next/link";
import type { ReactNode } from "react";
import NavLinks from "./NavLinks";

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="site">
      <header className="site-header">
        <Link href="/" className="brand">
          Lantern Books
        </Link>
        <nav aria-label="Main">
          <NavLinks />
        </nav>
      </header>
      <main>{children}</main>
      <footer className="site-footer">Lantern Books, 14 Quay Street. Open daily.</footer>
    </div>
  );
}
