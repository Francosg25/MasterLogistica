import { test, expect, Page } from "@playwright/test";
import { demoCatalogs, demoOwners, masterDemoShipments } from "../src/app/demo";
import { demoReport, demoInvoices } from "../src/app/finance-demo";
const row={...masterDemoShipments[0],reference_raw:"RM3-1616SI26-M23-MAT",parent_shipment_id:null,movement_number:null};
const owner=demoOwners.find(o=>o.analyst_code===3)!;
async function setup(page:Page) {
 await page.route("**/api/v1/**",async route=>{
  const path=new URL(route.request().url()).pathname.replace("/api/v1","");
  const json=(data:unknown,status=200)=>route.fulfill({json:data,status});
  if(path==="/auth/me") return json({id:owner.id,role:"SUPER_ADMIN",display_name:"Usuario de pruebas",email:"demo@example.com",analyst_code:3});
  if(path==="/references/catalogs") return json(demoCatalogs);
  if(path==="/suppliers") return json({items:[],total:0});
  if(path==="/masters/owners"||path==="/finance/owners") return json(demoOwners);
  if(path==="/workspace/overview") return json({month:"2026-10-01",active_references:24,live_provisions:3,settled_provisions:1,invoices_in_month:2,pending_invoices:0,totals:demoReport.totals,recent:[{id:row.id,reference:row.reference_raw,owner_name:"DENI",business_unit:"M23",status:"IN_TRANSIT"}]});
  if(path==="/masters/shipments") return json({items:[row],total:1,limit:50,offset:0});
  if(path==="/masters/summary") return json({total:1,by_status:{IN_TRANSIT:1}});
  if(path==="/finance/balances") return json({items:demoReport.balances,total:4,totals:demoReport.totals});
  if(path==="/finance/invoices") return json({items:demoInvoices,total:2});
  if(path==="/finance/history") return json({items:[],total:0});
  if(path==="/finance/report") return json(demoReport);
  if(path==="/finance/references") return json([{id:row.id,reference:row.reference_raw,owner_name:"DENI",company_code:"MXG",business_unit:"M23"}]);
  if(path===`/finance/references/${row.id}/activity`) return json({reference:row.reference_raw,provisions:[],invoices:[],history:{items:[],total:0}});
  if(path===`/shipments/${row.id}/family`) return json({root:row,classification:{process:"RM",operation:"SI",year:2026,business_unit:"M23",department:"MAT"},members:[{id:row.id,reference:row.reference_raw,owner_name:"DENI",status:"IN_TRANSIT",movement_number:null,is_current:true},{id:"child-1",reference:row.reference_raw+".1",owner_name:"DENI",status:"PLANNED",movement_number:1,is_current:false}]});
  return json({detail:"unexpected "+path},404);
 });
 await page.goto("/");
 await expect(page.getByRole("heading",{name:"Centro de referencias",exact:true})).toBeVisible();
}
async function navigate(page:Page,label:string){const menu=page.getByRole("button",{name:"Abrir navegación",exact:true});if(await menu.isVisible())await menu.click();await page.getByRole("navigation",{name:"Secciones"}).getByRole("button",{name:label,exact:true}).click();}

test("workspace puts reference activity, balances and next actions in one place",async({page})=>{
 await setup(page);
 await expect(page.locator(".overview-metrics")).toContainText("24");
 await expect(page.locator(".home-recent")).toContainText(row.reference_raw);
 await expect(page.locator(".home-balance")).toContainText("700.00");
 await page.screenshot({path:"test-results/workspace-home.png",fullPage:true});
 await navigate(page,"Referencias");
 await page.getByLabel("Responsable del master",{exact:true}).selectOption(owner.id);
 await expect(page.getByRole("grid",{name:"Embarques del master"})).toBeVisible();
 await page.screenshot({path:"test-results/workspace-references.png",fullPage:true});
 await navigate(page,"Consolidar");
 await expect(page.getByRole("heading",{name:"Consolidar facturas",exact:true})).toBeVisible();
 await expect(page.getByLabel("Archivo consolidado (.xlsx)")).toBeVisible();
 await page.screenshot({path:"test-results/workspace-consolidate.png",fullPage:true});
 await navigate(page,"Reporte mensual");
 await expect(page.locator(".report-balances")).toContainText("Liquidada");
 await page.screenshot({path:"test-results/workspace-report.png",fullPage:true});
});

test("command search opens a reference family and works from the keyboard",async({page})=>{
 await setup(page);
 await page.keyboard.press("Control+k");
 await page.getByLabel("Buscar referencia en todos los masters").fill("1616");
 const command=page.getByRole("dialog",{name:"Buscar referencia",exact:true});
 await expect(command.getByRole("option")).toHaveCount(1);
 await page.getByLabel("Buscar referencia en todos los masters").press("Enter");
 const activity=page.getByRole("dialog",{name:row.reference_raw,exact:true});
 await expect(activity.locator(".reference-family")).toContainText(row.reference_raw+".1");
 await expect(activity.getByRole("button",{name:"Añadir movimiento",exact:true})).toBeVisible();
 await page.screenshot({path:"test-results/workspace-reference-family.png",fullPage:true});
 await activity.getByRole("button",{name:"Historial",exact:true}).click();
 await expect(activity).toContainText("Sin cambios registrados.");
 await activity.getByRole("button",{name:"Cerrar movimientos",exact:true}).click();
 await expect(activity).toHaveCount(0);
});

test("mobile navigation opens and returns focus to a usable page without overflow",async({page})=>{
 await page.setViewportSize({width:390,height:844});
 await setup(page);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.screenshot({path:"test-results/workspace-mobile.png",fullPage:true});
 await navigate(page,"Reporte mensual");
 await expect(page.getByRole("heading",{name:"Reporte mensual",exact:true})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.getByRole("button",{name:"Abrir navegación",exact:true}).click();
 await expect(page.getByRole("navigation",{name:"Secciones"})).toBeVisible();
 await page.screenshot({path:"test-results/workspace-mobile-nav.png",fullPage:true});
 await page.getByRole("button",{name:"Cerrar navegación",exact:true}).click();
 await expect(page.getByRole("navigation",{name:"Secciones"})).toBeHidden();
});
