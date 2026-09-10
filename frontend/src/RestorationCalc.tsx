import IaaiCalculator from "./IaaiCalculator";

/** Калькулятор по ссылке Copart / IAAI / Bid.cars — без ленты поиска. */
export default function RestorationCalc() {
  return (
    <main className="page-main">
      <div className="calc-page">
        <div className="calc-toolbar calc-toolbar-title">
          <div className="calc-page-heading">
            <h1 className="calc-page-title">Калькулятор восстановления</h1>
            <p className="hint calc-page-sub">
              Ссылка Copart.com / IAAI.com / Bid.cars → ставка, Title, доставка Klaipeda/Poti, растаможка РБ.
            </p>
          </div>
        </div>
        <IaaiCalculator variant="restoration" />
      </div>
    </main>
  );
}
