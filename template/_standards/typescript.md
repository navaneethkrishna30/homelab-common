## TypeScript and React

Based on [Twenty's style guide](https://docs.twenty.com/developers/contribute/style-guide), adapted to our stack:
React, Vite, TanStack Query, Tailwind with shadcn/ui, tsc and oxlint.

Enforced, so review never repeats it. Copy both base files from homelab-common `template/_standards/` into the app's
`web/` folder and extend them; `tsc -b` and `oxlint` must pass:

- `tsconfig.strict.json`: `strict` (always), `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`,
  `noImplicitReturns`, `noFallthroughCasesInSwitch`, `forceConsistentCasingInFileNames`, `noImplicitOverride`,
  `verbatimModuleSyntax`, `erasableSyntaxOnly` (no enums or namespaces).
- `oxlintrc.json`: no `any`, no `@ts-` comments, no `!` non-null assertions, `type` over `interface`, `import type`
  for types, optional chaining, no default exports (config files excepted), kebab-case file names, 300-line files,
  rules of hooks and exhaustive deps.

Review for the parts no tool checks:

- Types: prefer inference where it is safe; write types out at boundaries: component props, API responses and hook
  return values. A props type is `<Component>Props`, destructured in the signature; no `React.FC`.
- String-literal unions instead of enums.
- `??` for defaults, not `||`, unless a falsy value must fall through.
- Pass named props; no `{...props}` passthrough of a whole object (shadcn/ui primitives excepted).
- Server state lives in TanStack Query, local state in `useState`. No `useRef` as state, no `React.memo` by default,
  `useMemo` / `useCallback` only for a measured problem.
- Event handlers over `useEffect`; an effect only syncs with something outside React.
- Names: descriptive camelCase variables, PascalCase types and components, SCREAMING_SNAKE_CASE constants, handlers
  `handleX`, callback props `onX`.
- Styling: Tailwind with the theme's tokens; no hard-coded colours or pixel values outside the theme.
- Imports through the `@/` alias, not `../../`.
- Layout: `pages/` for routes, `components/` for shared pieces, `components/ui/` for shadcn/ui primitives (they import
  nothing from the app), `lib/` for code that isn't React.

Not adopted from Twenty: its ban on type-only imports (`verbatimModuleSyntax` requires them), Jotai, Linaria, GraphQL
folders, `.component.tsx` suffixes and the `modules/` layout; they don't match this stack.
