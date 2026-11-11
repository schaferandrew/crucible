import Link from "next/link";
import { useRouter } from "next/router";
import type { ReactNode } from "react";

const NAV = [
  { href: "/", label: "Books" },
  { href: "/search", label: "Search" },
  { href: "/about", label: "About" },
];

export default function Layout({ children }: { children: ReactNode }) {
  const { pathname } = useRouter();
  const isActive = (href: string) =>
    href === "/"
      ? pathname === "/" || pathname.startsWith("/books") || pathname.startsWith("/genres")
      : pathname.startsWith(href);

  return (
    <div className="site">
      <header className="site-header">
        <Link href="/" className="brand">
          Lantern Books
        </Link>
        <nav aria-label="Main">
          {NAV.map(({ href, label }) => (
            <Link key={href} href={href} aria-current={isActive(href) ? "page" : undefined}>
              {label}
            </Link>
          ))}
        </nav>
      </header>
      <main>{children}</main>
      <footer className="site-footer">Lantern Books, 14 Quay Street. Open daily.</footer>
    </div>
  );
}
