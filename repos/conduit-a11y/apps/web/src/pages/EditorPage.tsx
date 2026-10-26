import { type FormEvent, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { Toast } from "../components/Toast";

export function EditorPage() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const [form, setForm] = useState({ title: "", description: "", body: "", tags: "" });
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    api.article(slug).then((a) =>
      setForm({ title: a.title, description: a.description, body: a.body, tags: a.tagList.join(" ") }),
    );
  }, [slug]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      const fields = { title: form.title, description: form.description, body: form.body };
      const saved = slug
        ? await api.updateArticle(slug, fields)
        : await api.createArticle({ ...fields, tagList: form.tags.split(/\s+/).filter(Boolean) });
      setToast(slug ? "Article updated" : "Article published");
      setTimeout(() => navigate(`/article/${saved.slug}`), 1500);
    } catch (err) {
      setErrors(err instanceof ApiError ? err.errors : { body: [String(err)] });
    }
  }

  const field = (name: keyof typeof form) => ({
    value: form[name],
    onChange: (e: { target: { value: string } }) => setForm({ ...form, [name]: e.target.value }),
  });

  return (
    <form className="editor-page" onSubmit={submit}>
      <Toast message={toast} />
      <input aria-label="Article Title" placeholder="Article Title" {...field("title")} />
      {errors.title && <span className="field-error">{errors.title.join(", ")}</span>}
      <input aria-label="What's this article about?" placeholder="What's this article about?" {...field("description")} />
      {errors.description && <span className="field-error">{errors.description.join(", ")}</span>}
      <textarea aria-label="Write your article" placeholder="Write your article (in markdown)" {...field("body")} />
      {errors.body && <span className="field-error">{errors.body.join(", ")}</span>}
      {!slug && <input aria-label="Enter tags" placeholder="Enter tags" {...field("tags")} />}
      <button type="submit">Publish Article</button>
    </form>
  );
}
