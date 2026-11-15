import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { I18nProvider, useI18n } from "./index";

function Probe() {
  const { t, lang, setLang } = useI18n();
  return (
    <div>
      <span data-testid="lang">{lang}</span>
      <span data-testid="title">{t("app_title")}</span>
      <button onClick={() => setLang(lang === "cs" ? "en" : "cs")}>toggle</button>
    </div>
  );
}

describe("i18n", () => {
  it("default cs, toggle přepne na en a persistuje do localStorage", () => {
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("lang")).toHaveTextContent("cs");
    expect(screen.getByTestId("title")).toHaveTextContent(/Forenzní workbench/);
    fireEvent.click(screen.getByRole("button", { name: "toggle" }));
    expect(screen.getByTestId("lang")).toHaveTextContent("en");
    expect(localStorage.getItem("stopa.lang")).toBe("en");
  });

  it("neznámý klíč vrací klíč (fail-soft)", () => {
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    function Inner() {
      const ctx = useI18n();
      return <span data-testid="missing">{ctx.t("does_not_exist")}</span>;
    }
    render(<Inner />);
    expect(screen.getByTestId("missing")).toHaveTextContent("does_not_exist");
  });
});
