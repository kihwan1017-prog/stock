# Frontend ? User Web + Admin (STEP41+)

Next.js App Router ????.

## ??

```text
src/app/
  page.tsx              # ?? (User / Admin ??)
  (auth)/login          # ?? ??? (?? ??)
  (admin)/admin/...     # ??? ?? (/admin/*)
  (user)/user/...       # ??? User Web (/user/*)
src/shared/components/  # ?? UI (UnimplementedNotice ?)
src/features/user/      # User API ?????·??
```

## URL

| ?? | ?? |
|------|------|
| http://localhost:3000/ | ?? |
| http://localhost:3000/user/dashboard | User Web |
| http://localhost:3000/admin/dashboard | Admin |
| http://localhost:3000/login?portal=user | User ?? |
| http://localhost:3000/login?portal=admin | Admin ?? |

## ??

Backend? JWT/`/me`/???? API? **????**.  
`NEXT_PUBLIC_AUTH_MODE=disabled` ?? ?? ????? ?????.

## ??·??

```powershell
cd D:\Projects\stock-platform\frontend
npm install
npm run dev
```

Backend: `http://127.0.0.1:8000`  
OpenAPI: `http://127.0.0.1:8000/docs`

?? ??(Admin ??): [../docs/reference/STEP41_ADMIN_FOUNDATION.md](../docs/reference/STEP41_ADMIN_FOUNDATION.md)
