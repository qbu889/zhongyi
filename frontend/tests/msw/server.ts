import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

export const server = setupServer(
  http.get("/api/chat/sessions", () =>
    HttpResponse.json({ total: 0, limit: 50, offset: 0, items: [] })),
);
