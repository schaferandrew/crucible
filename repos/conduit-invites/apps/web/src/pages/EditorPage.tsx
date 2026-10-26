import { type FormEvent, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";

export function EditorPage() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const [form, setForm] = useState({ title: "", description: "", body: "", tags: "" });
  const [errors, setErrors] = useState<string[]>([]);

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
      navigate(`/article/${saved.slug}`);
    } catch (err) {
      setErrors(err instanceof ApiError ? err.message.split("; ") : [String(err)]);
    }
  }

  const field = (name: keyof typeof form) => ({
    value: form[name],
    onChange: (e: { target: { value: string } }) => setForm({ ...form, [name]: e.target.value }),
  });

  return (
    <form className="editor-page" onSubmit={submit}>
      {errors.length > 0 && (
        <ul role="alert">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      <input aria-label="Article Title" placeholder="Article Title" {...field("title")} />
      <input aria-label="What's this article about?" placeholder="What's this article about?" {...field("description")} />
      <textarea aria-label="Write your article" placeholder="Write your article (in markdown)" {...field("body")} />
      {!slug && <input aria-label="Enter tags" placeholder="Enter tags" {...field("tags")} />}
      <button type="submit">Publish Article</button>
    </form>
  );
}
