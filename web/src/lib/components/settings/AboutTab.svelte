<script lang="ts">
  import BookOpen from "@lucide/svelte/icons/book-open";
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import { Button } from "$lib/components/ui/button";
  import { app } from "$lib/app.svelte";
  import { t } from "$lib/i18n.svelte";
</script>

<div class="flex items-center gap-3 py-2">
  <img src="/icon.svg" alt="" class="size-10" />
  <div>
    <p class="font-semibold">{t("app.name")}</p>
    <p class="text-muted-foreground text-sm">{t("app.tagline")}</p>
  </div>
</div>
<p class="text-muted-foreground mt-2 text-sm">{app.cfg ? t("about.version", { v: app.cfg.version }) : ""} · {t("about.license")}</p>
<p class="text-muted-foreground mt-1 text-xs">{t("about.font")}</p>
<div class="mt-4 flex flex-wrap gap-2">
  <Button variant="outline" size="sm" href="/docs" target="_blank" rel="noopener"><BookOpen />{t("about.docs")}</Button>
  <Button variant="outline" size="sm" href="https://github.com/kurashizu/kdchat" target="_blank" rel="noopener"><ExternalLink />{t("about.github")}</Button>
</div>
