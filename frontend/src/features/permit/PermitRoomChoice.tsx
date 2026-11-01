"use client";

import { useId } from "react";
import { msg } from "@/i18n/core";
import { useI18n } from "@/i18n/useI18n";
import type { OfferedRoom, RoomOffer } from "./api";
import styles from "./Permit.module.css";

const TYPE_NAMES: Record<string, string> = {
  living: msg("Living room"),
  kitchen: msg("Kitchen"),
  bedroom: msg("Bedroom"),
  bathroom: msg("Bathroom"),
  hall: msg("Hall"),
  storage: msg("Store room"),
  office: msg("Office"),
  other: msg("Other"),
};
const WHY_NOT: Record<RoomOffer["excluded"][number]["reason"], string> = {
  type: msg("Not offered: {rooms} (they aren't divided into a bedroom)."),
  no_place: msg("Not offered: {rooms} (their place on the plan couldn't be read)."),
  same_as_another: msg("Not offered: {rooms} (HABITA can't tell them apart on the plan)."),
};

export function useFloorName() {
  const { t } = useI18n();
  return (floor: number | null) => (floor === null ? "" : floor === 0 ? t("Ground floor") : t("Floor {n}", { n: floor }));
}

/** The name of a room as read on the plan, or its type when no name was written. */
export function useRoomName() {
  const { t } = useI18n();
  return (room: { label: string; type?: string; type_label?: string }) =>
    room.label || t(room.type_label ?? TYPE_NAMES[room.type ?? "other"] ?? "Other");
}

/**
 * HR-012 (owner, 2026-11-01): the user picks the room to divide from the rooms read on the plan. Nothing is
 * preselected; only a living room, a bedroom or an office is offered; a very small room carries a warning.
 */
export function PermitRoomChoice({
  offer,
  floor,
  onFloor,
  roomId,
  onRoom,
  disabled,
}: {
  offer: RoomOffer;
  floor: string;
  onFloor: (floor: string) => void;
  roomId: string;
  onRoom: (id: string) => void;
  disabled: boolean;
}) {
  const { t } = useI18n();
  const id = useId();
  const floorName = useFloorName();
  const roomName = useRoomName();

  if (offer.status === "unreadable") {
    return (
      <p className={styles.fieldHint} role="status">
        {t("HABITA couldn't read the rooms of this plan, so the view with one more bedroom isn't available for it. The other plan views are.")}
      </p>
    );
  }
  const reasons = (Object.keys(WHY_NOT) as (keyof typeof WHY_NOT)[])
    .map((reason) => [reason, offer.excluded.filter((e) => e.reason === reason)] as const)
    .filter(([, rooms]) => rooms.length > 0);
  const why = reasons.map(([reason, rooms]) => (
    <p key={reason} className={styles.fieldHint}>
      {t(WHY_NOT[reason], { rooms: rooms.map((e) => roomName(e)).join(", ") })}
    </p>
  ));
  if (offer.status === "none") {
    // Codex hr012i-r2: allowed rooms may be left out for another reason (no place, can't be told apart), so each
    // reason is shown rather than one sentence about the room types.
    return (
      <div role="status">
        <p className={styles.fieldHint}>{t("No room on this plan can be offered for this view.")}</p>
        {why}
      </div>
    );
  }
  const several = offer.floors.length > 1;
  const shown: OfferedRoom[] = several ? (floor === "" ? [] : offer.rooms.filter((r) => String(r.floor) === floor)) : offer.rooms;

  return (
    <div className={styles.affordField}>
      {several && (
        <>
          <label className={styles.fieldLabel} htmlFor={`${id}-floor`}>
            {t("Which floor?")}
          </label>
          <select
            id={`${id}-floor`}
            value={floor}
            disabled={disabled}
            onChange={(e) => {
              onFloor(e.target.value);
              onRoom(""); // a room of another floor can't stay chosen
            }}
          >
            <option value="">{t("Choose a floor")}</option>
            {offer.floors.map((f) => (
              <option key={String(f)} value={String(f)}>
                {floorName(f)}
              </option>
            ))}
          </select>
        </>
      )}
      {(!several || floor !== "") && (
        <fieldset className={styles.field}>
          <legend className={styles.fieldLabel}>{t("Which room do you want to divide?")}</legend>
          <div className={styles.choices}>
            {shown.map((r) => (
              <div key={r.id}>
                <label className={styles.choice}>
                  <input
                    type="radio"
                    name={`${id}-room`}
                    value={r.id}
                    checked={roomId === r.id}
                    disabled={disabled}
                    onChange={() => onRoom(r.id)}
                  />
                  <span>
                    <strong>{roomName(r)}</strong>
                    {" · "}
                    {t(r.type_label)}
                    {r.area !== null && <> · {r.area} m²</>}
                    {" · "}
                    {t(r.place_label)}
                    {r.floor !== null && <> · {floorName(r.floor)}</>}
                    {r.largest && <> · {t("the largest")}</>}
                  </span>
                </label>
                {r.small && (
                  <p className={`${styles.fieldHint} ${styles.otherInput}`}>
                    {t("It may become too small for a bedroom; confirm the RGEU minimum areas with the Câmara.")}
                  </p>
                )}
              </div>
            ))}
            {shown.length === 0 && <p className={styles.fieldHint}>{t("No room on this floor can be divided into a bedroom.")}</p>}
          </div>
        </fieldset>
      )}
      {why}
      <p className={styles.fieldHint}>
        {t("The list was read from your plan and may have errors. If the room isn't in the list, this view isn't available for this plan.")}
      </p>
    </div>
  );
}
