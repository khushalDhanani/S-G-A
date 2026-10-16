package scratch;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import java.io.*;
import java.lang.instrument.Instrumentation;
import java.lang.reflect.Method;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;

public class SapBridgeAgentV8 {
    private static HttpServer server = null;
    private static ClassLoader sapClassLoader = null;
    private static String currentSnapshotId = "";
    private static Map<String, Object> lastObservedState = new HashMap<>();
    private static final Map<String, Object> componentMap = new ConcurrentHashMap<>();
    private static Object activeGrid = null;
    public static final int PORT = 49221;

    public static void agentmain(String agentArgs, Instrumentation inst) {
        new Thread(() -> {
            try {
                Method stopM = com.sun.net.httpserver.HttpServer.class.getMethod("stop", int.class);
                for (Class<?> c : inst.getAllLoadedClasses()) {
                    if (c.getName().contains("SapAgentServer") || c.getName().contains("SapBridgeAgent")) {
                        try {
                            java.lang.reflect.Field f = c.getDeclaredField("server");
                            f.setAccessible(true);
                            Object s = f.get(null);
                            if (s != null) {
                                stopM.invoke(s, 0);
                                f.set(null, null);
                            }
                        } catch (Throwable ignored) {}
                    }
                }

                for (Class<?> c : inst.getAllLoadedClasses()) {
                    if ("com.sap.platin.base.application.GuiApplication".equals(c.getName())) {
                        sapClassLoader = c.getClassLoader();
                        break;
                    }
                }

                if (sapClassLoader == null) {
                    System.err.println("[SapBridgeAgentV8] GuiApplication class not found!");
                    return;
                }

                server = HttpServer.create(new InetSocketAddress("127.0.0.1", PORT), 0);
                server.createContext("/health", new HealthHandler());
                server.createContext("/status", new HealthHandler());
                server.createContext("/observe", new ObserveHandler());
                server.createContext("/act", new ActHandler());
                server.createContext("/eval", new EvalHandler());
                server.createContext("/stop", new StopHandler());
                server.setExecutor(Executors.newCachedThreadPool());
                server.start();

                System.out.println("[SapBridgeAgentV8] Started on http://127.0.0.1:" + PORT);
            } catch (Throwable t) {
                t.printStackTrace();
            }
        }, "SapBridgeAgentV8-Thread").start();
    }

    private static Object getSession() throws Exception {
        ClassLoader oldCl = Thread.currentThread().getContextClassLoader();
        try {
            Thread.currentThread().setContextClassLoader(sapLoaderOrFallback());
            Class<?> appCls = Class.forName("com.sap.platin.base.application.GuiApplication", true, sapClassLoader);
            Method m = appCls.getMethod("currentApplication");
            Object app = m.invoke(null);
            if (app == null) return null;
            Method getConns = app.getClass().getMethod("getConnections");
            Object conns = getConns.invoke(app);
            if (conns == null) return null;
            Method elemAt = conns.getClass().getMethod("elementAt", int.class);
            Object conn = elemAt.invoke(conns, 0);
            if (conn == null) return null;
            Method getChildren = conn.getClass().getMethod("getChildren");
            Object sessions = getChildren.invoke(conn);
            if (sessions == null) return null;
            Method sessElem = sessions.getClass().getMethod("elementAt", int.class);
            return sessElem.invoke(sessions, 0);
        } finally {
            Thread.currentThread().setContextClassLoader(oldCl);
        }
    }

    static class HealthHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            try {
                Object sess = getSession();
                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("ok", true);
                if (sess != null) {
                    Object info = sess.getClass().getMethod("getInfo").invoke(sess);
                    resp.put("system", getProp(info, "getSystemName"));
                    resp.put("client", getProp(info, "getClient"));
                    resp.put("user", getProp(info, "getUser"));
                    resp.put("transaction", getProp(info, "getTransaction"));
                    resp.put("program", getProp(info, "getProgram"));
                    Object wnd0 = sess.getClass().getMethod("findById", String.class).invoke(sess, "wnd[0]");
                    if (wnd0 != null) {
                        resp.put("title", getProp(wnd0, "getText"));
                    }
                }
                sendJson(exchange, 200, toJson(resp));
            } catch (Throwable t) {
                sendJson(exchange, 500, "{\"ok\":false,\"error\":\"" + escapeJson(t.getMessage()) + "\"}");
            }
        }
    }

    static class ObserveHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            try {
                Object sess = getSession();
                if (sess == null) {
                    sendJson(exchange, 500, "{\"error\":\"No active SAP session found\"}");
                    return;
                }
                Map<String, Object> state = observeScreen(sess);
                sendJson(exchange, 200, toJson(state));
            } catch (Throwable t) {
                t.printStackTrace();
                sendJson(exchange, 500, "{\"error\":\"" + escapeJson(t.getMessage()) + "\"}");
            }
        }
    }

    static class StopHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            sendJson(exchange, 200, "{\"ok\":true,\"stopped\":true}");
            new Thread(() -> {
                try { Thread.sleep(200); } catch (InterruptedException ignored) {}
                if (server != null) {
                    try {
                        com.sun.net.httpserver.HttpServer.class.getMethod("stop", int.class).invoke(server, 0);
                    } catch (Throwable ignored) {}
                    server = null;
                }
            }).start();
        }
    }

    static class EvalHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            try {
                if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                    sendJson(exchange, 405, "{\"error\":\"Method not allowed\"}");
                    return;
                }
                String body = readBody(exchange.getRequestBody());
                String script = extractJsonString(body, "script");
                if (script == null) script = "";

                Object sess = getSession();
                if (sess == null) {
                    sendJson(exchange, 500, "{\"error\":\"No active SAP session found\"}");
                    return;
                }

                ClassLoader oldCl = Thread.currentThread().getContextClassLoader();
                try {
                    Thread.currentThread().setContextClassLoader(sapLoaderOrFallback());
                    Class<?> interpCls = Class.forName("com.sap.platin.base.scripting.javaScript.JavaScriptInterpreter", true, sapClassLoader);
                    Class<?> sessCls = Class.forName("com.sap.platin.base.session.GuiSession", true, sapClassLoader);
                    Object interp = interpCls.getConstructor(sessCls).newInstance(sess);
                    Method proc = interpCls.getMethod("processScript", String.class);
                    Object res = proc.invoke(interp, script);
                    Map<String, Object> resp = new HashMap<>();
                    resp.put("result", res != null ? res.toString() : "");
                    sendJson(exchange, 200, toJson(resp));
                } finally {
                    Thread.currentThread().setContextClassLoader(oldCl);
                }
            } catch (Throwable t) {
                sendJson(exchange, 500, "{\"error\":\"" + escapeJson(t.getMessage()) + "\"}");
            }
        }
    }

    static class ActHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendJson(exchange, 405, "{\"error\":\"Method not allowed\"}");
                return;
            }
            try {
                String body = readBody(exchange.getRequestBody());
                String reqSnapshotId = extractJsonString(body, "snapshot_id");
                if (reqSnapshotId == null || !reqSnapshotId.equals(currentSnapshotId)) {
                    sendJson(exchange, 200, "{\"error\":\"Stale snapshot_id; observe the screen again before acting.\"}");
                    return;
                }

                Object sess = getSession();
                if (sess == null) {
                    sendJson(exchange, 500, "{\"error\":\"No active SAP session found\"}");
                    return;
                }

                List<Map<String, Object>> actions = parseActions(body);
                for (Map<String, Object> act : actions) {
                    applyAction(sess, act);
                }

                Thread.sleep(200); // Wait for GUI settling
                Map<String, Object> newState = observeScreen(sess);
                sendJson(exchange, 200, toJson(newState));
            } catch (Throwable t) {
                t.printStackTrace();
                sendJson(exchange, 500, "{\"error\":\"" + escapeJson(t.getMessage()) + "\"}");
            }
        }
    }

    private static void applyAction(Object sess, Map<String, Object> act) throws Exception {
        String op = (String) act.get("op");
        if ("open_tx".equals(op)) {
            String tx = (String) act.get("transaction");
            if (tx == null) tx = "";
            tx = tx.trim();
            if (!tx.startsWith("/n") && !tx.startsWith("/N")) {
                tx = "/n" + tx;
            }
            Method sendCmd = sess.getClass().getMethod("sendCommand", String.class);
            sendCmd.invoke(sess, tx);
        } else if ("set_field".equals(op)) {
            String target = (String) act.get("target");
            Object valObj = act.get("value");
            String val = valObj != null ? valObj.toString() : "";
            Object comp = resolveComponent(target);
            if (comp == null) {
                throw new IllegalArgumentException("Target field not found: " + target);
            }
            try {
                comp.getClass().getMethod("setText", String.class).invoke(comp, val);
            } catch (Throwable t) {
                try {
                    comp.getClass().getMethod("setCurText", String.class).invoke(comp, val);
                } catch (Throwable t2) {
                    try {
                        comp.getClass().getMethod("setValue", String.class).invoke(comp, val);
                    } catch (Throwable t3) {
                        comp.getClass().getMethod("setSelected", boolean.class).invoke(comp, "true".equalsIgnoreCase(val) || "1".equals(val));
                    }
                }
            }
        } else if ("press".equals(op)) {
            String target = (String) act.get("target");
            Object comp = resolveButton(target);
            if (comp == null) {
                comp = resolveComponent(target);
            }
            if (comp == null) {
                throw new IllegalArgumentException("Target button not found: " + target);
            }
            try {
                comp.getClass().getMethod("press").invoke(comp);
            } catch (Throwable t) {
                try {
                    comp.getClass().getMethod("select").invoke(comp);
                } catch (Throwable t2) {
                    try {
                        comp.getClass().getMethod("setSelected", boolean.class).invoke(comp, true);
                    } catch (Throwable t3) {
                        throw new RuntimeException("Could not press or select " + target + ": " + t.getMessage(), t);
                    }
                }
            }
        } else if ("vkey".equals(op)) {
            Object keyObj = act.get("key");
            int key = 0;
            if (keyObj instanceof Number) key = ((Number) keyObj).intValue();
            else if (keyObj != null) key = Integer.parseInt(keyObj.toString().trim());

            Object activeWnd = getActiveWindow(sess);
            activeWnd.getClass().getMethod("sendVKey", int.class).invoke(activeWnd, key);
        } else if ("select_rows".equals(op)) {
            Object rowsObj = act.get("rows");
            List<Integer> rows = new ArrayList<>();
            if (rowsObj instanceof List) {
                for (Object o : (List<?>) rowsObj) {
                    if (o instanceof Number) rows.add(((Number) o).intValue());
                    else if (o != null) {
                        try { rows.add(Integer.parseInt(o.toString().trim())); } catch (Throwable ignored) {}
                    }
                }
            } else if (rowsObj != null) {
                String str = rowsObj.toString().replace("[", "").replace("]", "").replace("\"", "");
                for (String p : str.split("[,;]")) {
                    p = p.trim();
                    if (!p.isEmpty()) try { rows.add(Integer.parseInt(p)); } catch(Throwable ignored) {}
                }
            }
            if (activeGrid != null) {
                StringBuilder sb = new StringBuilder();
                for (int i = 0; i < rows.size(); i++) {
                    if (i > 0) sb.append(";");
                    sb.append(rows.get(i));
                }
                try {
                    Object bean = activeGrid.getClass().getMethod("getBean").invoke(activeGrid);
                    if (bean != null) {
                        try {
                            bean.getClass().getMethod("setPersonasSelectedRows", String.class).invoke(bean, sb.toString());
                        } catch (Throwable t2) {
                            bean.getClass().getMethod("setSelectedRowsS", String.class).invoke(bean, sb.toString().replace(';', ','));
                        }
                    }
                } catch (Throwable t) {
                    try {
                        activeGrid.getClass().getMethod("setSelectedRows", String.class).invoke(activeGrid, sb.toString());
                    } catch (Throwable ignored) {}
                }
            }
        }
    }

    private static Object getActiveWindow(Object sess) throws Exception {
        Method findById = sess.getClass().getMethod("findById", String.class);
        for (int i = 9; i >= 1; i--) {
            try {
                Object wnd = findById.invoke(sess, "wnd[" + i + "]");
                if (wnd != null) return wnd;
            } catch(Throwable ignored) {}
        }
        return findById.invoke(sess, "wnd[0]");
    }

    private static Object resolveComponent(String target) {
        if (target == null || target.isEmpty()) return null;

        // Exact match in componentMap
        Object comp = componentMap.get(target);
        if (comp != null) return comp;

        comp = componentMap.get(target.toLowerCase());
        if (comp != null) return comp;

        // Try suffix or substring
        for (Map.Entry<String, Object> e : componentMap.entrySet()) {
            String k = e.getKey();
            if (k.endsWith(target) || k.equalsIgnoreCase(target) || k.contains(target)) {
                return e.getValue();
            }
        }
        return null;
    }

    private static Object resolveButton(String target) {
        if (target == null || target.isEmpty()) return null;
        String lower = target.toLowerCase().trim();

        // Standard SAP shortcuts
        if ("execute".equals(lower) || "f8".equals(lower)) {
            Object b = componentMap.get("execute");
            if (b != null) return b;
        }
        if ("enter".equals(lower)) {
            Object b = componentMap.get("enter");
            if (b != null) return b;
        }
        if ("save".equals(lower)) {
            Object b = componentMap.get("save");
            if (b != null) return b;
        }
        if ("back".equals(lower)) {
            Object b = componentMap.get("back");
            if (b != null) return b;
        }
        if ("cancel".equals(lower)) {
            Object b = componentMap.get("cancel");
            if (b != null) return b;
        }
        if ("exit".equals(lower)) {
            Object b = componentMap.get("exit");
            if (b != null) return b;
        }
        if ("find".equals(lower)) {
            Object b = componentMap.get("find");
            if (b != null) return b;
        }

        return resolveComponent(target);
    }

    private static Map<String, Object> observeScreen(Object sess) throws Exception {
        ClassLoader oldCl = Thread.currentThread().getContextClassLoader();
        try {
            Thread.currentThread().setContextClassLoader(sapLoaderOrFallback());
            Map<String, Object> state = new LinkedHashMap<>();
            Object info = sess.getClass().getMethod("getInfo").invoke(sess);
            state.put("transaction", getProp(info, "getTransaction"));
            state.put("system", getProp(info, "getSystemName"));
            state.put("client", getProp(info, "getClient"));
            state.put("user", getProp(info, "getUser"));

            Method findById = sess.getClass().getMethod("findById", String.class);
            Object wnd0 = findById.invoke(sess, "wnd[0]");
            String title = wnd0 != null ? getProp(wnd0, "getText") : "";
            state.put("title", title);

            // Check modal popup
            boolean popupOpen = false;
            String popupTitle = "";
            Object modalWnd = null;
            for (int i = 1; i <= 5; i++) {
                try {
                    Object mw = findById.invoke(sess, "wnd[" + i + "]");
                    if (mw != null) {
                        popupOpen = true;
                        modalWnd = mw;
                        popupTitle = getProp(mw, "getText");
                        break;
                    }
                } catch(Throwable ignored) {}
            }
            state.put("popup_open", popupOpen);
            state.put("popup_title", popupTitle);

            // Status bar
            String statusBarText = "";
            String statusType = "";
            try {
                Object sbar = findById.invoke(sess, "wnd[0]/sbar");
                if (sbar != null) {
                    statusBarText = getProp(sbar, "getMessageText");
                    if (statusBarText == null || statusBarText.isEmpty()) {
                        statusBarText = getProp(sbar, "getText");
                    }
                    statusType = getProp(sbar, "getMessageType");
                }
            } catch(Throwable ignored) {}
            state.put("status_bar", statusBarText != null ? statusBarText.trim() : "");
            state.put("status_type", statusType != null ? statusType.trim() : "");

            // Clear component map and active grid
            componentMap.clear();
            activeGrid = null;

            // Collect elements
            List<Map<String, Object>> elements = new ArrayList<>();
            Object rootToScan = popupOpen ? modalWnd : wnd0;
            scanTree(rootToScan, elements, 0);

            // Enrich field labels and friendly aliases
            enrichElementLabels(elements);

            currentSnapshotId = UUID.randomUUID().toString();
            state.put("snapshot_id", currentSnapshotId);
            state.put("elements", elements);

            lastObservedState = state;
            return state;
        } finally {
            Thread.currentThread().setContextClassLoader(oldCl);
        }
    }

    private static ClassLoader sapLoaderOrFallback() {
        return sapClassLoader != null ? sapClassLoader : Thread.currentThread().getContextClassLoader();
    }

    private static void scanTree(Object comp, List<Map<String, Object>> elements, int depth) {
        if (comp == null || depth > 12) return;
        try {
            String id = getProp(comp, "getId");
            String type = getProp(comp, "getType");
            String text = getProp(comp, "getText");
            String tooltip = getProp(comp, "getTooltip");
            String name = getProp(comp, "getName");

            if (text == null || text.isEmpty()) {
                text = getProp(comp, "getCurText");
            }
            if (text == null || text.isEmpty()) {
                text = getProp(comp, "getDisplayedText");
            }

            if (id != null && !id.isEmpty()) {
                componentMap.put(id, comp);
            }

            if (type != null) {
                if (type.contains("TextField") || type.contains("PasswordField")) {
                    Map<String, Object> f = new LinkedHashMap<>();
                    f.put("id", id);
                    f.put("type", "field");
                    f.put("value", text != null ? text.trim() : "");
                    f.put("tooltip", tooltip != null ? tooltip.trim() : "");
                    f.put("name", name != null ? name.trim() : "");
                    try {
                        Method isChangeable = comp.getClass().getMethod("isChangeable");
                        f.put("changeable", isChangeable.invoke(comp));
                    } catch(Throwable t) {
                        f.put("changeable", true);
                    }
                    elements.add(f);

                    // Add name to map
                    if (name != null && !name.isEmpty()) componentMap.put(name, comp);
                } else if (type.contains("Button")) {
                    Map<String, Object> b = new LinkedHashMap<>();
                    b.put("id", id);
                    b.put("type", "button");
                    String label = (text != null && !text.trim().isEmpty()) ? text.trim() : (tooltip != null ? tooltip.trim() : "");
                    b.put("label", label);
                    b.put("tooltip", tooltip != null ? tooltip.trim() : "");
                    elements.add(b);

                    if (!label.isEmpty()) {
                        componentMap.put(label.toLowerCase(), comp);
                    }
                    if (id != null) {
                        if (id.endsWith("btn[8]")) componentMap.put("execute", comp);
                        else if (id.endsWith("btn[0]")) componentMap.put("enter", comp);
                        else if (id.endsWith("btn[11]")) componentMap.put("save", comp);
                        else if (id.endsWith("btn[3]")) componentMap.put("back", comp);
                        else if (id.endsWith("btn[12]")) componentMap.put("cancel", comp);
                        else if (id.endsWith("btn[15]")) componentMap.put("exit", comp);
                        else if (id.endsWith("btn[71]")) componentMap.put("find", comp);
                    }
                } else if (type.contains("RadioButton") || type.contains("CheckBox")) {
                    Map<String, Object> r = new LinkedHashMap<>();
                    r.put("id", id);
                    r.put("type", type.contains("Radio") ? "radio" : "checkbox");
                    String rlabel = text != null && !text.trim().isEmpty() ? text.trim() : (tooltip != null ? tooltip.trim() : "");
                    r.put("label", rlabel);
                    try {
                        Method isSel = comp.getClass().getMethod("isSelected");
                        r.put("selected", isSel.invoke(comp));
                    } catch(Throwable ignored) {}
                    elements.add(r);
                    if (name != null && !name.isEmpty()) componentMap.put(name, comp);
                    if (!rlabel.isEmpty()) componentMap.put(rlabel.toLowerCase(), comp);
                } else if (type.contains("GridView") || type.contains("Shell")) {
                    String subtype = getProp(comp, "getSubtype");
                    Object bean = null;
                    try {
                        bean = comp.getClass().getMethod("getBean").invoke(comp);
                    } catch(Throwable ignored) {}

                    if ("GridView".equals(subtype) || (bean != null && bean.getClass().getName().contains("Grid"))) {
                        activeGrid = comp;
                        Object targetBean = bean != null ? bean : comp;
                        try {
                            Method getRowCount = targetBean.getClass().getMethod("getRowCount");
                            int rows = (Integer) getRowCount.invoke(targetBean);
                            Map<String, Object> g = new LinkedHashMap<>();
                            g.put("id", id);
                            g.put("type", "grid");
                            g.put("subtype", subtype);
                            g.put("row_count", rows);

                            List<String> cols = new ArrayList<>();
                            Map<String, String> colTitles = new LinkedHashMap<>();
                            try {
                                Method getColOrder = targetBean.getClass().getMethod("getColumnOrder");
                                Object colOrderObj = getColOrder.invoke(targetBean);
                                if (colOrderObj != null) {
                                    Method lenM = colOrderObj.getClass().getMethod("getLength");
                                    int clen = (Integer) lenM.invoke(colOrderObj);
                                    Method elemAt = colOrderObj.getClass().getMethod("elementAt", int.class);
                                    Method getDispTitle = null;
                                    try {
                                        getDispTitle = targetBean.getClass().getMethod("getDisplayedColumnTitle", String.class);
                                    } catch(Throwable ignored) {}

                                    for (int ci = 0; ci < clen; ci++) {
                                        String colId = elemAt.invoke(colOrderObj, ci).toString();
                                        cols.add(colId);
                                        String colTitle = colId;
                                        if (getDispTitle != null) {
                                            try {
                                                Object ct = getDispTitle.invoke(targetBean, colId);
                                                if (ct != null && !ct.toString().trim().isEmpty()) {
                                                    colTitle = ct.toString().trim();
                                                }
                                            } catch(Throwable ignored) {}
                                        }
                                        colTitles.put(colId, colTitle);
                                    }
                                }
                            } catch(Throwable ignored) {}
                            g.put("columns", cols);
                            g.put("column_titles", colTitles);

                            // Extract rows (up to 50)
                            List<Map<String, String>> rowList = new ArrayList<>();
                            int maxR = Math.min(rows, 50);
                            Method getCellVal = null;
                            try {
                                getCellVal = targetBean.getClass().getMethod("getCellValue", int.class, String.class);
                            } catch(Throwable ignored) {}

                            if (getCellVal != null) {
                                for (int ri = 0; ri < maxR; ri++) {
                                    Map<String, String> rowMap = new LinkedHashMap<>();
                                    for (String col : cols) {
                                        try {
                                            Object cv = getCellVal.invoke(targetBean, ri, col);
                                            rowMap.put(col, cv != null ? cv.toString().trim() : "");
                                        } catch(Throwable ignored) {}
                                    }
                                    rowList.add(rowMap);
                                }
                            }
                            g.put("rows", rowList);

                            // Selected rows
                            List<Integer> selectedRows = new ArrayList<>();
                            try {
                                Method getSel = targetBean.getClass().getMethod("getPersonasSelectedRows");
                                Object selObj = getSel.invoke(targetBean);
                                if (selObj != null) {
                                    for (String part : selObj.toString().split("[;,]")) {
                                        part = part.trim();
                                        if (!part.isEmpty()) {
                                            selectedRows.add(Integer.parseInt(part));
                                        }
                                    }
                                }
                            } catch(Throwable ignored) {}
                            g.put("selected_rows", selectedRows);

                            elements.add(g);
                        } catch(Throwable ignored) {}
                    }
                }
            }

            // Recurse children
            try {
                Method getChildren = comp.getClass().getMethod("getChildren");
                Object children = getChildren.invoke(comp);
                if (children != null) {
                    Method getLen = children.getClass().getMethod("getLength");
                    int len = (Integer) getLen.invoke(children);
                    Method childAt = children.getClass().getMethod("elementAt", int.class);
                    for (int i = 0; i < len; i++) {
                        scanTree(childAt.invoke(children, i), elements, depth + 1);
                    }
                }
            } catch(NoSuchMethodException ignored) {}
        } catch(Throwable ignored) {}
    }

    private static void enrichElementLabels(List<Map<String, Object>> elements) {
        for (Map<String, Object> el : elements) {
            String id = (String) el.get("id");
            if (id == null) continue;

            String tip = (String) el.getOrDefault("tooltip", "");
            String name = (String) el.getOrDefault("name", "");

            if ("field".equals(el.get("type"))) {
                String label = tip;
                String pos = "value";
                if (id.endsWith("-LOW") || id.contains("LOW")) pos = "from";
                else if (id.endsWith("-HIGH") || id.contains("HIGH")) pos = "to";

                if (id.contains("AUDAT") || tip.toLowerCase().contains("document date")) {
                    label = "Document Date";
                    if (pos.equals("from")) componentMap.put("document_date_from", componentMap.get(id));
                    if (pos.equals("to")) componentMap.put("document_date_to", componentMap.get(id));
                } else if (id.contains("VKORG") || tip.toLowerCase().contains("sales organization")) {
                    label = "Sales Organization";
                    componentMap.put("sales_org", componentMap.get(id));
                } else if (id.contains("VTWEG") || tip.toLowerCase().contains("distribution channel")) {
                    label = "Distribution Channel";
                } else if (id.contains("SPART") || tip.toLowerCase().contains("division")) {
                    label = "Division";
                } else if (id.contains("KUNNR") || tip.toLowerCase().contains("sold-to")) {
                    label = "Sold-To Party";
                } else if (id.contains("MATNR") || tip.toLowerCase().contains("material")) {
                    label = "Material";
                }

                if (label == null || label.isEmpty()) {
                    label = name;
                }
                el.put("label", label != null ? label : "");
                el.put("position", pos);

                Object comp = componentMap.get(id);
                if (comp != null) {
                    componentMap.put(label.toLowerCase(), comp);
                    componentMap.put(label.toLowerCase() + ":" + pos, comp);
                }
            }
        }
    }

    private static String getProp(Object obj, String methodName) {
        if (obj == null) return "";
        try {
            Method m = obj.getClass().getMethod(methodName);
            Object res = m.invoke(obj);
            return res != null ? res.toString() : "";
        } catch(Throwable t) {
            return "";
        }
    }

    private static void sendJson(HttpExchange exchange, int status, String json) throws IOException {
        byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=UTF-8");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    private static String readBody(InputStream is) throws IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int r;
        while ((r = is.read(buf)) != -1) {
            bos.write(buf, 0, r);
        }
        return bos.toString(StandardCharsets.UTF_8);
    }

    private static String extractJsonString(String json, String key) {
        String pattern = "\"" + key + "\"";
        int idx = json.indexOf(pattern);
        if (idx == -1) return null;
        int colon = json.indexOf(':', idx + pattern.length());
        if (colon == -1) return null;
        int quoteStart = json.indexOf('"', colon);
        if (quoteStart == -1) return null;
        int quoteEnd = json.indexOf('"', quoteStart + 1);
        if (quoteEnd == -1) return null;
        return json.substring(quoteStart + 1, quoteEnd);
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> parseActions(String json) {
        List<Map<String, Object>> list = new ArrayList<>();
        int actionsIdx = json.indexOf("\"actions\"");
        if (actionsIdx == -1) return list;
        int arrStart = json.indexOf('[', actionsIdx);
        int arrEnd = json.lastIndexOf(']');
        if (arrStart == -1 || arrEnd <= arrStart) return list;

        String sub = json.substring(arrStart + 1, arrEnd);
        int depth = 0;
        int objStart = -1;
        for (int i = 0; i < sub.length(); i++) {
            char c = sub.charAt(i);
            if (c == '{') {
                if (depth == 0) objStart = i;
                depth++;
            } else if (c == '}') {
                depth--;
                if (depth == 0 && objStart != -1) {
                    String objStr = sub.substring(objStart, i + 1);
                    Map<String, Object> map = parseSimpleObject(objStr);
                    list.add(map);
                    objStart = -1;
                }
            }
        }
        return list;
    }

    private static Map<String, Object> parseSimpleObject(String objStr) {
        Map<String, Object> map = new LinkedHashMap<>();
        String[] pairs = objStr.replaceAll("[{}\"]", "").split(",");
        for (String pair : pairs) {
            String[] kv = pair.split(":", 2);
            if (kv.length == 2) {
                String k = kv[0].trim();
                String v = kv[1].trim();
                if ("rows".equals(k)) {
                    // Handled below
                } else {
                    map.put(k, v);
                }
            }
        }
        if (objStr.contains("\"rows\"")) {
            int rIdx = objStr.indexOf("\"rows\"");
            int b1 = objStr.indexOf('[', rIdx);
            int b2 = objStr.indexOf(']', b1);
            if (b1 != -1 && b2 > b1) {
                String rowArr = objStr.substring(b1 + 1, b2).trim();
                List<Integer> rowList = new ArrayList<>();
                if (!rowArr.isEmpty()) {
                    for (String s : rowArr.split(",")) {
                        try {
                            rowList.add(Integer.parseInt(s.trim()));
                        } catch(Throwable ignored) {}
                    }
                }
                map.put("rows", rowList);
            }
        }
        return map;
    }

    private static String toJson(Object obj) {
        if (obj == null) return "null";
        if (obj instanceof String) return "\"" + escapeJson((String) obj) + "\"";
        if (obj instanceof Number || obj instanceof Boolean) return obj.toString();
        if (obj instanceof Map) {
            StringBuilder sb = new StringBuilder("{");
            boolean first = true;
            for (Map.Entry<?, ?> e : ((Map<?, ?>) obj).entrySet()) {
                if (!first) sb.append(",");
                first = false;
                sb.append("\"").append(escapeJson(e.getKey().toString())).append("\":");
                sb.append(toJson(e.getValue()));
            }
            sb.append("}");
            return sb.toString();
        }
        if (obj instanceof List) {
            StringBuilder sb = new StringBuilder("[");
            boolean first = true;
            for (Object item : (List<?>) obj) {
                if (!first) sb.append(",");
                first = false;
                sb.append(toJson(item));
            }
            sb.append("]");
            return sb.toString();
        }
        return "\"" + escapeJson(obj.toString()) + "\"";
    }

    private static String escapeJson(String s) {
        if (s == null) return "";
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '"') sb.append("\\\"");
            else if (c == '\\') sb.append("\\\\");
            else if (c == '\b') sb.append("\\b");
            else if (c == '\f') sb.append("\\f");
            else if (c == '\n') sb.append("\\n");
            else if (c == '\r') sb.append("\\r");
            else if (c == '\t') sb.append("\\t");
            else if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
            else sb.append(c);
        }
        return sb.toString();
    }
}
