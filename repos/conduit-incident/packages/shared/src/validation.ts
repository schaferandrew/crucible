import { z } from "zod";

// Request bodies, as the RealWorld spec wraps them ({ user: {...} }, { article: {...} }, ...).

export const registerSchema = z.object({
  user: z.object({
    username: z.string().trim().min(1, "can't be blank").max(40),
    email: z.string().trim().email("is invalid"),
    password: z.string().min(8, "is too short (minimum is 8 characters)"),
  }),
});

export const loginSchema = z.object({
  user: z.object({
    email: z.string().trim().min(1, "can't be blank"),
    password: z.string().min(1, "can't be blank"),
  }),
});

export const updateUserSchema = z.object({
  user: z
    .object({
      username: z.string().trim().min(1).max(40),
      email: z.string().trim().email("is invalid"),
      password: z.string().min(8, "is too short (minimum is 8 characters)"),
      bio: z.string().max(2000).nullable(),
      image: z.string().url("is not a URL").nullable(),
    })
    .partial(),
});

const tagList = z.array(z.string().trim().min(1).max(40)).max(10).default([]);

export const createArticleSchema = z.object({
  article: z.object({
    title: z.string().trim().min(1, "can't be blank").max(200),
    description: z.string().trim().min(1, "can't be blank").max(500),
    body: z.string().min(1, "can't be blank"),
    tagList,
  }),
});

export const updateArticleSchema = z.object({
  article: z
    .object({
      title: z.string().trim().min(1, "can't be blank").max(200),
      description: z.string().trim().min(1, "can't be blank").max(500),
      body: z.string().min(1, "can't be blank"),
    })
    .partial(),
});

export const createCommentSchema = z.object({
  comment: z.object({
    body: z.string().trim().min(1, "can't be blank").max(5000),
  }),
});

export type RegisterInput = z.infer<typeof registerSchema>["user"];
export type LoginInput = z.infer<typeof loginSchema>["user"];
export type UpdateUserInput = z.infer<typeof updateUserSchema>["user"];
export type CreateArticleInput = z.infer<typeof createArticleSchema>["article"];
export type UpdateArticleInput = z.infer<typeof updateArticleSchema>["article"];
export type CreateCommentInput = z.infer<typeof createCommentSchema>["comment"];

/** zod issues in the RealWorld error envelope: { field: ["message", ...] }. */
export function toErrorEnvelope(error: z.ZodError): Record<string, string[]> {
  const errors: Record<string, string[]> = {};
  for (const issue of error.issues) {
    const field = String(issue.path[issue.path.length - 1] ?? "body");
    (errors[field] ??= []).push(issue.message);
  }
  return errors;
}
