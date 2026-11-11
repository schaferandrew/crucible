"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", label: "Books" },
  { href: "/search", label: "Search" },
  { href: "/about", label: "About" },
];

export default function NavLinks() {
  const pathname = usePathname();
  const isActive = (href: string) =>
    href === "/"
      ? pathname === "/" || pathname.startsWith("/books") || pathname.startsWith("/genres")
      : pathname.startsWith(href);

  return (
    <>
      {NAV.map(({ href, label }) => (
        <Link key={href} href={href} aria-current={isActive(href) ? "page" : undefined}>
          {label}
        </Link>
      ))}
    </>
  );
}
