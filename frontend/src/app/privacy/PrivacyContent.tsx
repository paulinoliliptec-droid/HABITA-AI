"use client";

import Link from "next/link";
import { useI18n } from "@/i18n/useI18n";
import styles from "./page.module.css";

export function PrivacyContent() {
  const { t } = useI18n();
  return (
    <main className={styles.page}>
      <article className={styles.article}>
        <p className={styles.eyebrow}>{t("Hackathon preview")}</p>
        <h1 className={styles.title}>{t("Privacy & terms")}</h1>
        <p className={styles.lead}>
          {t("HABITA AI is a preview built for the Meta Global AI Developer Hackathon. It is decision support, not legal advice: always confirm requirements with the competent authority.")}
        </p>

        <section className={styles.section}>
          <h2>{t("What happens when you search")}</h2>
          <ul>
            <li>
              {t("As you type, the text is sent to Google Maps Platform (Places API) to suggest addresses. Choosing or submitting an address sends it to the HABITA server, which looks it up with the Google Geocoding API.")}
            </li>
            <li>{t("The map is displayed with the Google Maps JavaScript API.")}</li>
            <li>{t("Your permit questions are sent to Google Cloud Translation to recognise their language. When you read HABITA in Portuguese, answers and reports are also sent there to be translated; they are not stored by HABITA in translated form.")}</li>
            <li>{t("HABITA has no accounts and does not ask for your name, email or other personal details.")}</li>
          </ul>
        </section>

        <section className={styles.section}>
          <h2>{t("What HABITA stores")}</h2>
          <ul>
            <li>
              {t("Each resolved address is saved as a property record in our database (MongoDB Atlas): the address you entered, Google place identifiers, the resolved address and coordinates, and the jurisdiction HABITA derived from them.")}
            </li>
            <li>
              {t("Content obtained from Google (address, coordinates and the jurisdiction derived from them) expires after 30 days. Expired content is never shown: it is fetched again from Google when you open the property, and it is removed from our database by a best-effort clean-up that runs whenever the service starts and periodically while it runs. Place identifiers are kept so the property can be refreshed.")}
            </li>
            <li>
              {t("Property links are not private: anyone with a property link can open it. Don't enter an address you wouldn't want shared.")}
            </li>
            <li>{t("To have a property record removed, contact the project owner.")}</li>
          </ul>
        </section>

        <section className={styles.section}>
          <h2>{t("Google Maps")}</h2>
          <p>
            {t("By using HABITA you also agree to the")}{" "}
            <a href="https://maps.google.com/help/terms_maps/" rel="noopener noreferrer" target="_blank">
              {t("Google Maps/Google Earth Additional Terms of Service")}
            </a>{" "}
            {t("and acknowledge the")}{" "}
            <a href="https://policies.google.com/privacy" rel="noopener noreferrer" target="_blank">
              {t("Google Privacy Policy")}
            </a>
            .
          </p>
        </section>

        <Link href="/" className={styles.back}>
          {t("Back to HABITA")}
        </Link>
      </article>
    </main>
  );
}
