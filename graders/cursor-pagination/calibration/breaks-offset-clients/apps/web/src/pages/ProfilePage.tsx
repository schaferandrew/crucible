import type { ArticleListQuery, Profile } from "@conduit/shared";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ArticleList } from "../components/ArticleList";

export function ProfilePage() {
  const { username = "" } = useParams();
  const { user } = useAuth();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [tab, setTab] = useState<"author" | "favorited">("author");

  useEffect(() => {
    api.profile(username).then(setProfile, () => setProfile(null));
  }, [username]);

  const load = useCallback(
    (page: Pick<ArticleListQuery, "limit" | "cursor">) => api.articles({ ...page, [tab]: username }),
    [tab, username],
  );

  async function toggleFollow() {
    if (!profile) return;
    setProfile(profile.following ? await api.unfollow(username) : await api.follow(username));
  }

  if (!profile) return <p>Loading…</p>;
  return (
    <div className="profile-page">
      <h1>{profile.username}</h1>
      {profile.bio && <p>{profile.bio}</p>}
      {user && user.username !== username && (
        <button type="button" onClick={toggleFollow}>
          {profile.following ? `Unfollow ${username}` : `Follow ${username}`}
        </button>
      )}
      <nav>
        <button type="button" aria-pressed={tab === "author"} onClick={() => setTab("author")}>
          My Articles
        </button>
        <button type="button" aria-pressed={tab === "favorited"} onClick={() => setTab("favorited")}>
          Favorited Articles
        </button>
      </nav>
      <ArticleList key={tab} load={load} />
    </div>
  );
}
