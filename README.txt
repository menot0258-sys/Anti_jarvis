JARVIS - minimal local AI assistant (clay / Gemini-style UI)
1. Install Python 3 (nothing else needed).
2. Windows: double-click run.bat   |   Linux/macOS: ./run.sh
3. It prints a URL and opens it. Open Settings: every integration explains WHY Jarvis needs it. Only the AI brain key is required.

AUTO-APPROVE: header toggle (on by default) runs commands/emails without asking. If a prompt appears, click "Always approve" to stop it asking again.
LIVE CALL: always listening, interrupt him anytime, fullscreen orb. Esc ends it. Headphones recommended.
COPY: every command card has Copy command / Copy output / Run again; file cards have Open / Edit / Copy path; AI replies have a copy icon on hover.
RICH ANSWERS: replies render headings, tables, lists, quotes, clickable links, LaTeX formulas ($x^2$, $$...$$) and dark code blocks with syntax colours + Copy code. He speaks only a short summary, not the tables/code. Formulas use KaTeX when online, with a built-in offline renderer as fallback.
DESIGN: clay + Gemini-style UI, big glowing orb on the start screen that shrinks as you chat, live status pill (Ready/Listening/Thinking/Working/Speaking), avatars on replies, suggestion chips, mobile-friendly.
TERMINAL: the Terminal button opens a REAL persistent shell (bash PTY on Linux/macOS; cmd on Windows). You type in it AND Jarvis runs his commands in it, so you watch him work live; cd and environment carry over. Ctrl+C / Clear / Copy / Restart buttons, drag its top bar to resize, Up/Down = history. It is line-based: full-screen programs (vim, top) are not supported.
PALETTE: Ctrl+K opens a command palette (toggle terminal/editor/theme, new chat, live call, personalities...).
Command and output blocks are dark; chat sits in a solid panel with fading edges; Settings > Appearance has accent colours and reduce-motion.
GOOGLE WORKSPACE (Settings > Google Workspace): lets Jarvis create Google Slides decks (themes, tables, images, speaker notes), Sheets (formulas, styled tables, charts), Forms and graded quizzes, Docs, Calendar events with Meet links, Drive upload/share/search, Gmail, and any other Google API (Tasks, Contacts...). One-time setup (~5 min): create a Google Cloud project, enable the APIs (links in the card), make an OAuth client of type "Desktop app", paste its Client ID + secret, press Connect Google. Tokens are stored in google_auth.json next to server.py (keep it private; delete it to sign out). Tip: Publish the OAuth app so the login doesn't expire after 7 days.
THEME: sun/moon button switches dark and light clay themes. Stop button appears while he is busy.
TOKENS: Settings > External services lets you add GITHUB_TOKEN, VERCEL_TOKEN etc. They are passed to commands he runs (git push, deploy).
Everything he creates is saved in "apps/" and served at http://127.0.0.1:PORT/apps/<project>/<file>.
Editor: Darcula + minimap + live preview (built-in editor fallback offline). Ctrl+S save, Ctrl+I edit with AI, Ctrl+K focus chat.
Type !command to run a command yourself (Up/Down arrows recall history). Drag files onto the page to upload.
Self-edit: he can read and edit his own source (@self/index.html, @self/server.py).
