<script lang="ts">
  // the recent messages, newest first: click to edit; translations under the text; revert / send again
  import Ellipsis from "@lucide/svelte/icons/ellipsis";
  import MessageSquareText from "@lucide/svelte/icons/message-square-text";
  import MonitorSmartphone from "@lucide/svelte/icons/monitor-smartphone";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Repeat from "@lucide/svelte/icons/repeat-2";
  import Trash2 from "@lucide/svelte/icons/trash-2";
  import Undo2 from "@lucide/svelte/icons/undo-2";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import * as Card from "$lib/components/ui/card";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import { app, type Message } from "$lib/app.svelte";
  import { ask } from "$lib/confirm.svelte";
  import { t } from "$lib/i18n.svelte";
  import { cn } from "$lib/utils";

  const hhmm = (iso: string) => {
    const d = new Date(iso);
    return isNaN(+d) ? "" : d.toTimeString().slice(0, 5);
  };
  const tag = (c: string) => ({ zh: "ZH", zh_hant: "ZH-T" } as Record<string, string>)[c] ?? c.toUpperCase();

  async function revert(m: Message) {
    if (await ask({ title: t("hist.confirmRevertTitle"), desc: t("hist.confirmRevert"), action: t("hist.revert") })) app.revert(m);
  }
  async function clearAll() {
    if (await ask({ title: t("hist.confirmClearTitle"), desc: t("hist.confirmClear"), action: t("hist.clear") })) app.clearHistory();
  }
</script>

<Card.Root class="gap-0 py-0">
  <Card.Header class="flex flex-row items-center justify-between border-b px-4 !py-3">
    <Card.Title class="text-sm">{t("hist.title")}</Card.Title>
    {#if app.history.length}
      <Button variant="ghost" size="xs" class="text-muted-foreground" onclick={clearAll}><Trash2 />{t("hist.clear")}</Button>
    {/if}
  </Card.Header>
  <Card.Content class="p-0">
    {#if !app.history.length}
      <p class="text-muted-foreground px-4 py-10 text-center text-sm">{t("hist.empty")}</p>
    {:else}
      <ul class="divide-y">
        {#each app.history as m (m.id)}
          {@const can = app.editable(m)}
          {@const current = app.cur?.id === m.id}
          <li class={cn("group relative flex gap-3 px-4 py-3 transition-colors", can && "hover:bg-muted/40", current && "bg-primary/5")}>
            <button type="button" class="min-w-0 flex-1 text-left disabled:cursor-default" disabled={!can}
              onclick={() => app.startEdit(m)} title={can ? t("hist.edit") : undefined}>
              <p class={cn("break-words whitespace-pre-wrap", m.reverted && "text-muted-foreground line-through")}>{m.text}</p>
              {#each Object.entries(m.translations || {}) as [code, tr] (code)}
                <p class="text-muted-foreground mt-1 flex gap-2 text-sm">
                  <span class="mt-0.5 shrink-0 text-[10px] font-semibold tracking-wide">{tag(code)}</span>
                  <span class="min-w-0 break-words">{tr}</span>
                </p>
              {/each}
              <div class="text-muted-foreground mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
                <span class="tabular-nums">{hhmm(m.created_at)}</span>
                {#if m.targets?.includes("chatbox")}<MessageSquareText class="size-3.5" aria-label={t("hist.chatbox")} />{/if}
                {#if m.targets?.includes("kd")}<MonitorSmartphone class="size-3.5" aria-label={t("hist.kd")} />{/if}
                {#if m.final === false}<Badge variant="secondary">{t("hist.typing")}</Badge>
                {:else if m.reverted}<Badge variant="outline">{t("hist.reverted")}</Badge>
                {:else if m.edited}<Badge variant="outline">{t("hist.edited")}</Badge>{/if}
              </div>
            </button>
            <div class="flex shrink-0 items-start gap-0.5 opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
              {#if can}
                <Button size="icon-sm" variant="ghost" aria-label={t("hist.edit")} title={t("hist.edit")} onclick={() => app.startEdit(m)}
                  class="max-sm:hidden"><Pencil /></Button>
              {/if}
              <DropdownMenu.Root>
                <DropdownMenu.Trigger>
                  {#snippet child({ props })}
                    <Button {...props} size="icon-sm" variant="ghost" aria-label={t("hist.more")}><Ellipsis /></Button>
                  {/snippet}
                </DropdownMenu.Trigger>
                <DropdownMenu.Content align="end" class="w-56">
                  {#if can}
                    <DropdownMenu.Item onclick={() => app.startEdit(m)}><Pencil />{t("hist.edit")}</DropdownMenu.Item>
                  {/if}
                  <DropdownMenu.Item onclick={() => app.again(m)}><Repeat />{t("hist.again")}</DropdownMenu.Item>
                  {#if m.kd_id != null && !m.reverted && m.final !== false}
                    <DropdownMenu.Separator />
                    <DropdownMenu.Item variant="destructive" onclick={() => revert(m)} title={t("hist.revertTip")}>
                      <Undo2 />{t("hist.revert")}</DropdownMenu.Item>
                  {/if}
                </DropdownMenu.Content>
              </DropdownMenu.Root>
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  </Card.Content>
</Card.Root>
