import { Link, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { ArticlePage } from "./pages/ArticlePage";
import { EditorPage } from "./pages/EditorPage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { MyArticlesPage } from "./pages/MyArticlesPage";
import { ProfilePage } from "./pages/ProfilePage";
import { ReviewQueuePage } from "./pages/ReviewQueuePage";

export function App() {
  const { user, logout } = useAuth();
  return (
    <>
      <header className="navbar">
        <Link to="/">conduit</Link>
        <nav>
          <Link to="/">Home</Link>
          {user ? (
            <>
              <Link to="/editor">New Article</Link>
              <Link to="/my-articles">My Articles</Link>
              <Link to="/review">Review</Link>
              <Link to={`/profile/${user.username}`}>{user.username}</Link>
              <button type="button" onClick={logout}>Sign out</button>
            </>
          ) : (
            <Link to="/login">Sign in</Link>
          )}
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/editor" element={<EditorPage />} />
          <Route path="/editor/:slug" element={<EditorPage />} />
          <Route path="/article/:slug" element={<ArticlePage />} />
          <Route path="/profile/:username" element={<ProfilePage />} />
          <Route path="/my-articles" element={<MyArticlesPage />} />
          <Route path="/review" element={<ReviewQueuePage />} />
        </Routes>
      </main>
    </>
  );
}
