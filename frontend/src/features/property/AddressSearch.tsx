"use client";

import { useRouter } from "next/navigation";
import { useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { useI18n } from "@/i18n/useI18n";
import { ApiError } from "@/lib/api";
import { cycleIndex } from "@/lib/cycleIndex";
import { resolveLocation } from "./api";
import type { ResolveLocationInput } from "./types";
import { usePlaceSuggestions, type PlaceSuggestion } from "./usePlaceSuggestions";
import styles from "./AddressSearch.module.css";

interface AddressSearchProps {
  variant?: "hero" | "compact";
  autoFocus?: boolean;
  /** Sample addresses offered under the field (hero only). */
  examples?: readonly string[];
}

/** Address combobox: suggests places as you type, resolves on submit, then opens the workspace. */
export function AddressSearch({ variant = "hero", autoFocus = false, examples }: AddressSearchProps) {
  const { t } = useI18n();
  const router = useRouter();
  const ids = { input: useId(), listbox: useId(), error: useId() };
  const inputRef = useRef<HTMLInputElement>(null);

  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { suggestions, available, endSession } = usePlaceSuggestions(resolving ? "" : query);
  // The highlight belongs to one suggestion list; a new list starts unhighlighted.
  const [active, setActive] = useState<{ list: readonly PlaceSuggestion[]; index: number }>({ list: [], index: -1 });
  const activeIndex = active.list === suggestions ? active.index : -1;
  const setActiveIndex = (index: number) => setActive({ list: suggestions, index });
  const listVisible = open && suggestions.length > 0;
  const activeSuggestion = listVisible && activeIndex >= 0 ? suggestions[activeIndex] : undefined;

  async function resolve(input: ResolveLocationInput) {
    setResolving(true);
    setError(null);
    setOpen(false);
    try {
      const property = await resolveLocation(input);
      endSession();
      const target = `/property/${property.property_id}`;
      // Match quality belongs to this request, so it travels with this navigation.
      const href = property.partial_match ? `${target}?match=partial` : target;
      if (window.location.pathname === target) {
        // Already on this property: the workspace re-renders from the property store.
        router.replace(href);
        setQuery("");
      } else {
        router.push(href, { transitionTypes: ["open-property"] });
      }
      // Release the form on every successful path; a retained component must not stay busy.
      setResolving(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("Something went wrong. Please try again."));
      setResolving(false);
      inputRef.current?.focus();
    }
  }

  function choose(suggestion: PlaceSuggestion) {
    setQuery(suggestion.full);
    void resolve({ place_id: suggestion.placeId });
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (resolving) return;
    if (activeSuggestion) return choose(activeSuggestion);
    const address = query.trim();
    if (address.length < 3) {
      setError(t("Enter a full address, including the street and town."));
      return;
    }
    void resolve({ address });
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!suggestions.length) return;
      event.preventDefault();
      setOpen(true);
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActiveIndex(cycleIndex(activeIndex, step, suggestions.length));
    } else if (event.key === "Escape" && listVisible) {
      event.preventDefault();
      setOpen(false);
      setActiveIndex(-1);
    }
  }

  return (
    <form className={`${styles.search} ${styles[variant]}`} onSubmit={onSubmit} role="search" noValidate>
      <label htmlFor={ids.input} className={variant === "hero" ? styles.label : "visually-hidden"}>
        {t("Property address")}
      </label>

      <div className={styles.control} data-busy={resolving || undefined}>
        <Icon name="pin" size={variant === "hero" ? 20 : 18} className={styles.leadingIcon} />
        <input
          ref={inputRef}
          id={ids.input}
          className={styles.input}
          type="text"
          inputMode="search"
          autoComplete="off"
          spellCheck={false}
          autoFocus={autoFocus}
          placeholder={variant === "hero" ? t("Enter a property address") : t("Search another address")}
          value={query}
          disabled={resolving}
          role="combobox"
          aria-expanded={listVisible}
          aria-controls={ids.listbox}
          aria-autocomplete={available ? "list" : "none"}
          aria-activedescendant={activeSuggestion ? `${ids.listbox}-${activeIndex}` : undefined}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? ids.error : undefined}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            setActiveIndex(-1);
            setError(null);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
        />
        <Button type="submit" size={variant === "hero" ? "lg" : "md"} loading={resolving} className={styles.submit}>
          {resolving ? t("Resolving") : variant === "hero" ? t("Resolve") : t("Go")}
          {!resolving && <Icon name="arrowRight" size={16} />}
        </Button>

        <ul id={ids.listbox} role="listbox" aria-label={t("Address suggestions")} className={styles.listbox} hidden={!listVisible}>
          {suggestions.map((s, i) => (
            <li
              key={s.placeId}
              id={`${ids.listbox}-${i}`}
              role="option"
              aria-selected={i === activeIndex}
              className={styles.option}
              // Keep focus in the input; select on mousedown before blur closes the list.
              onMouseDown={(e) => {
                e.preventDefault();
                choose(s);
              }}
              onMouseEnter={() => setActiveIndex(i)}
            >
              <span className={styles.optionPrimary}>{s.primary}</span>
              {s.secondary && <span className={styles.optionSecondary}>{s.secondary}</span>}
            </li>
          ))}
          <li role="presentation" className={styles.attribution}>
            {t("Suggestions from Google Maps")}
          </li>
        </ul>
      </div>

      <p id={ids.error} className={styles.error} aria-live="polite">
        {error}
      </p>

      {variant === "hero" && examples?.length ? (
        <div className={styles.examples}>
          <span className={styles.examplesLabel}>{t("Try")}</span>
          {examples.map((example) => (
            <button
              key={example}
              type="button"
              className={styles.example}
              disabled={resolving}
              onClick={() => {
                setQuery(example);
                void resolve({ address: example });
              }}
            >
              {example}
            </button>
          ))}
        </div>
      ) : null}
    </form>
  );
}
