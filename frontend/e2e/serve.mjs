// Local static server for checking the production build, including its real auth provider.
import http from "node:http";
import { readFile } from "node:fs/promises";
import { resolve, extname, sep } from "node:path";
const root = resolve("dist/web/browser");
const types = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
};
http
  .createServer(async (req, res) => {
    const path = resolve(
      root,
      "." + new URL(req.url, "http://localhost").pathname,
    );
    if (path !== root && !path.startsWith(root + sep)) {
      res.writeHead(403).end();
      return;
    }
    try {
      const file = path === root ? resolve(root, "index.html") : path;
      const content = await readFile(file);
      res.writeHead(200, {
        "Content-Type": types[extname(file)] ?? "application/octet-stream",
      });
      res.end(content);
    } catch {
      res.writeHead(404).end();
    }
  })
  .listen(4301, "127.0.0.1");
