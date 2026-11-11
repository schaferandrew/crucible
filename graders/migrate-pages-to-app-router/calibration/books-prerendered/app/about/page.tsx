import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "About",
  description: "Who we are, where to find us and when we are open.",
};

export default function About() {
  return (
    <>
      <h1>About Lantern Books</h1>
      <p>Lantern Books is a small independent shop on Quay Street, run by two booksellers since 2009.</p>
      <h2>Opening hours</h2>
      <ul>
        <li>Monday to Friday: 9am to 6pm</li>
        <li>Saturday: 10am to 5pm</li>
        <li>Sunday: 11am to 3pm</li>
      </ul>
    </>
  );
}
