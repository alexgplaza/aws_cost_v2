function compareMonths() {
    const current = document.getElementById("currentMonth").value;
    const compare = document.getElementById("compareMonth").value;

    fetch("/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current, compare })
    })
    .then(res => res.json())
    .then(data => {
      const tbody = document.getElementById("comparisonTableBody");
      tbody.innerHTML = "";

      data.forEach(row => {
        const diff = parseFloat(row.Difference || 0);
        const pct = parseFloat(row.Percentage || 0);

        const diffClass = diff > 0 ? "diff-positive" : "diff-negative";
        const pctClass = pct > 0 ? "diff-positive" : "diff-negative";

        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${row.Account}</td>
          <td class="${diffClass}">${diff.toFixed(2)}</td>
          <td class="${pctClass}">${pct.toFixed(2)}%</td>
        `;
        tbody.appendChild(tr);
      });

      document.getElementById("comparisonResults").style.display = "block";
    })
    .catch(error => {
      alert("Error comparing months. Please check the console for details.");
      console.error(error);
    });
}

document.addEventListener("DOMContentLoaded", () => {
    const selector = document.getElementById("accountSelector");
    if (selector) {
        selector.addEventListener("change", function () {
            const selected = this.value;

            fetch("/account_graph", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ account: selected })
            })
            .then(res => res.json())
            .then(data => {
                if (!data || !data.stacked || !data.donut) {
                    console.warn("No data for selected account");
                    return;
                }

                // Graficar la de barras apiladas
                Plotly.newPlot("accountChartContainer", data.stacked.data, data.stacked.layout, {responsive: true});

                // Graficar el donut
                Plotly.newPlot("donutChartContainer", data.donut.data, data.donut.layout, {responsive: true});
                document.getElementById("donutContainer").style.display = "block";
            })
            .catch(err => {
                console.error("Error fetching account data:", err);
            });
        });
        if (selector.options.length === 1) {
            selector.selectedIndex = 0;
            selector.dispatchEvent(new Event("change"));
        }
    }

    if (typeof stackedBar !== "undefined") {
        Plotly.newPlot("stackedBarChart", stackedBar.data, stackedBar.layout, {responsive: true});
    }

        // Resize automáticamente
    window.addEventListener("resize", () => {
        Plotly.Plots.resize(document.getElementById("stackedBarChart"));
        Plotly.Plots.resize(document.getElementById("accountChartContainer"));
        Plotly.Plots.resize(document.getElementById("donutChartContainer"));
    });


  });


// Mostrar/ocultar sección de presupuesto
function toggleBudgetSection() {
    const section = document.getElementById("budgetSection");
    const arrow = document.getElementById("arrowToggle");
    const visible = section.style.display === "block";
    section.style.display = visible ? "none" : "block";
    arrow.textContent = visible ? "▼" : "▲";
}

// Activar botón solo si hay valor
document.addEventListener("DOMContentLoaded", () => {
    const input = document.getElementById("fiscalBudget");
    const button = document.getElementById("calculateBudgetBtn");

    if (input && button) {
        input.addEventListener("input", () => {
            button.disabled = input.value.trim() === "";
        });

        button.addEventListener("click", () => {
            const budget = parseFloat(input.value);
            if (isNaN(budget) || budget <= 0) {
                alert("Please enter a valid positive budget.");
                return;
            }

            fetch("/fiscal_usage", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ budget })
            })
            .then(res => res.json())
            .then(data => {
                const spent = data.total_spent;
                const used_pct = data.used_pct;

                document.getElementById("spentAmount").textContent = `${spent.toFixed(2)} €`;

                const bar = document.getElementById("budgetProgress");
                bar.style.width = `${used_pct}%`;
                bar.textContent = `${used_pct}%`;

                if (used_pct >= 90) {
                    bar.className = "progress-bar bg-danger";
                } else if (used_pct >= 70) {
                    bar.className = "progress-bar bg-warning";
                } else {
                    bar.className = "progress-bar bg-success";
                }

                document.getElementById("budgetResult").style.display = "block";
            })
            .catch(error => {
                console.error("Error calculating fiscal usage:", error);
                alert("Something went wrong calculating budget usage.");
            });
        });
    }
});


