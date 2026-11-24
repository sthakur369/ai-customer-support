"""Interactive customer support application."""
import json
import re
import time
import threading

from config.settings import (ACTIVE_ML_MODEL, LLM_MODEL, LLM_PROVIDER, EMBEDDING_MODEL, RERANKER_MODEL, RAG_ENABLED, ML_INTERVENTION_CONFIDENCE_THRESHOLD,
                              MAX_QUERY_LENGTH, VECTOR_TOP_K, RERANK_TOP_K, MAX_CONTEXT_CHARS)
from model_training.inference import predict_query, _artifacts, _hf_artifacts
from llm.client import get_client
from llm.lifecycle import (
    security_assessment, route_to_rag, compose_final_response, build_admin_packet,
    enforce_retrieved_policy_escalation,
)
from rag.service import load_rag_runtime, load_document_catalog, retrieve_and_rerank
from database.db import (start_db, stop_db, check_db, validate_login,
                         get_customer_context, get_recent_customer_orders)
from app.ticket_service import (
    initialize_support_schema, create_conversation, get_conversation,
    get_active_conversation, append_message, update_state, select_order,
    close_conversation, escalate_conversation, close_inactive_conversations,
)
from app.order_context import resolve_order_context
from app.message_routing import is_small_talk, small_talk_response


def show(stage: str, payload: dict) -> None:
    print(f"\n[{stage}]")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def startup() -> None:
    print("\nCustomer Support | AI Support")
    print("Loading configured models...", flush=True)
    if ACTIVE_ML_MODEL == "huggingface":
        from model_training.model_downloader import ensure_hf_model_ready
        ensure_hf_model_ready()
        _hf_artifacts()
    else:
        _artifacts()
    get_client()  # Initialize the provider client; no request is sent yet.
    print(f"ML: {ACTIVE_ML_MODEL} | LLM: {LLM_MODEL}")
    try:
        runtime = load_rag_runtime()
        if runtime:
            count = runtime[2].count()
            print(f"RAG: ready ({count} indexed chunks)" if count else "RAG: initialized (0 indexed chunks; ingest policies before policy questions)")
        else:
            print("RAG: disabled")
    except Exception as exc:
        print(f"RAG: unavailable at startup ({type(exc).__name__}); policy queries will fail safely")
    catalog_count = len(load_document_catalog())
    print(f"Knowledge documents: {catalog_count} | ML intervention confidence: {ML_INTERVENTION_CONFIDENCE_THRESHOLD:.2f}")
    print(f"RAG window: vector top-k={VECTOR_TOP_K} -> reranker top-k={RERANK_TOP_K} | max context={MAX_CONTEXT_CHARS} chars")
    print("Ready. Type 'exit' to quit.\n")


def answer_question(question: str, customer_id: int, order_id: str | None,
                    db_connection) -> dict:
    total_started = time.perf_counter()
    if not question.strip():
        return {"status": "REFUSED", "message": "Please enter a question.", "latency_seconds": 0.0}
    if len(question) > MAX_QUERY_LENGTH:
        return {"status": "REFUSED", "message": f"Question exceeds {MAX_QUERY_LENGTH} characters.", "latency_seconds": 0.0}

    if is_small_talk(question):
        response = small_talk_response(question)
        print("\n[FAST PATH] Greeting/pleasantry detected; ML, security LLM, RAG and escalation stages skipped.")
        show("DIRECT RESPONSE", response)
        return response

    print("\nProcessing question...")
    print("1/5 ML classification", end="... ", flush=True)
    ml, ml_latency = predict_query(question)
    ml["latency_seconds"] = ml_latency
    show("ML CLASSIFICATION", ml)

    # Fetch authenticated customer/order context before intervention assessment.
    # The intervention LLM also needs this context to avoid asking for
    # information already provided during order selection.
    customer_context = get_customer_context(
        customer_id, order_id, db_connection
    )

    if customer_context is None:
        response = {
            "status": "ERROR",
            "message": "Customer or selected order could not be verified. Please log in again.",
            "latency_seconds": round(time.perf_counter() - total_started, 4),
        }
        show("CUSTOMER CONTEXT ERROR", response)
        return response

    show("VERIFIED CUSTOMER CONTEXT", customer_context)

    print("2/5 Security and intervention assessment", end="... ", flush=True)
    intervention, security, security_latency = security_assessment( question, ml, customer_context )
    show("SECURITY ASSESSMENT", security)
    show("LLM INTERVENTION DECISION", intervention)
    if intervention["decision"] == "REFUSE":
        response = {
            "status": "REFUSED", "decision": "REFUSE",
            "message": "I cannot fulfill this request.",
            "evidence": security.get("evidence", []), "citations": [],
            "human_intervention_required": False,
            "security_termination": bool(security.get("blocked")),
            "latency_seconds": round(time.perf_counter()-total_started, 4),
        }
        show("FINAL RESPONSE", response)
        return response
    if intervention["human_intervention_required"] or intervention["decision"] == "ESCALATE":
        # Collect policy evidence for the reviewer even when the customer-facing
        # flow is being handed off. Failure to retrieve must not block escalation.
        routing, retrieval = None, None
        try:
            routing, _ = route_to_rag(question, ml, customer_context)
            if routing.get("rag_required"):
                rag_result, rag_latency = retrieve_and_rerank(
                    question, routing.get("relevant_document_ids"), routing.get("search_query")
                )
                retrieval = {**rag_result, "latency_seconds": rag_latency}
        except Exception as exc:
            retrieval = {"status": "ERROR", "chunks": [], "evidence": [],
                         "error": f"Evidence retrieval unavailable: {type(exc).__name__}"}
        admin = build_admin_packet(
            question, ml, intervention, security, routing, retrieval,
            intervention.get("reason") or "Human intervention requested."
        )
        show("HUMAN REVIEW REQUIRED", {"decision": "ESCALATE", "latency_seconds": security_latency, "admin_evidence": admin})
        return {"status": "ESCALATED", "admin_evidence": admin,
                "total_latency_seconds": round(time.perf_counter()-total_started, 4)}
    if intervention["decision"] == "CLARIFY":
        response = {"status": "NEEDS_CLARIFICATION", "decision": "CLARIFY",
                    "message": intervention.get("reason") or "Could you share a little more detail?",
                    "evidence": intervention.get("evidence", []), "citations": [],
                    "human_intervention_required": False,
                    "latency_seconds": round(time.perf_counter()-total_started, 4)}
        show("FINAL RESPONSE", response)
        return response

    # Resolve order selection before routing so factual order questions do not
    # depend on policy retrieval and the LLM never guesses among multiple orders.
    customer_context, clarification = resolve_order_context(question, ml, customer_context)
    if clarification is not None:
        clarification["latency_seconds"] = round(time.perf_counter() - total_started, 4)
        clarification["stage_latencies_seconds"] = {"ml": ml_latency}
        clarification["total_latency_seconds"] = clarification["latency_seconds"]
        show("ORDER CLARIFICATION REQUIRED", clarification)
        return clarification

    print("3/5 Checking whether company knowledge is required", end="... ", flush=True)
    routing, routing_latency = route_to_rag(question, ml, customer_context)
    show("KNOWLEDGE ROUTING", routing)
    retrieval = {"status": "NOT_REQUIRED", "chunks": [], "evidence": [], "latency_seconds": 0.0}
    if routing["rag_required"]:
        print("4/5 Retrieving and reranking policy evidence", end="... ", flush=True)
        try:
            rag_result, rag_latency = retrieve_and_rerank(
                question, routing["relevant_document_ids"], routing.get("search_query")
            )
            retrieval = {**rag_result, "latency_seconds": rag_latency}
        except Exception as exc:
            retrieval = {"status": "ERROR", "chunks": [], "evidence": [],
                         "error": f"RAG unavailable: {type(exc).__name__}", "latency_seconds": 0.0}
        show("RAG RETRIEVAL / RERANKING", {
            "status": retrieval["status"], "evidence": retrieval.get("evidence", []),
            "latency_seconds": retrieval["latency_seconds"],
        })
        if retrieval["status"] in {"ERROR", "KNOWLEDGE_BASE_EMPTY", "DISABLED"}:
            reason = "Company policy evidence is required but the knowledge base is unavailable."
            intervention_for_admin = {**intervention, "human_intervention_required": True,
                                      "decision": "ESCALATE", "reason": reason,
                                      "queue": "Knowledge Support"}
            admin = build_admin_packet(question, ml, intervention_for_admin, security,
                                       routing, retrieval, reason)
            show("HUMAN REVIEW REQUIRED", {"decision": "ESCALATE", "admin_evidence": admin,
                                           "latency_seconds": retrieval["latency_seconds"]})
            return {"status": "ESCALATED", "admin_evidence": admin,
                    "total_latency_seconds": round(time.perf_counter()-total_started, 4)}

        # Apply explicit policy triggers using the customer's own message plus
        # the reranked policy chunks. This prevents the final-response model
        # from silently contradicting a policy-mandated handoff.
        intervention = enforce_retrieved_policy_escalation(question, intervention, retrieval)
        if intervention.get("human_intervention_required"):
            admin = build_admin_packet(
                question, ml, intervention, security, routing, retrieval,
                intervention.get("reason") or "Policy requires human review."
            )
            show("HUMAN REVIEW REQUIRED", {
                "decision": "ESCALATE", "intervention_assessment": intervention,
                "admin_evidence": admin,
                "latency_seconds": retrieval["latency_seconds"],
            })
            return {"status": "ESCALATED", "admin_evidence": admin,
                    "total_latency_seconds": round(time.perf_counter()-total_started, 4)}

    print("5/5 Composing customer response", end="... ", flush=True)
    # Fetch only this logged-in customer's relevant context after RAG has completed.
    # The database helpers constrain every query by the authenticated customer ID.
    # customer_context = get_customer_context(customer_id, order_id, db_connection)
    if customer_context is None:
        response = {
            "status": "ERROR",
            "message": "Customer context could not be verified. Please log in again.",
            "latency_seconds": round(time.perf_counter()-total_started, 4),
        }
        show("CUSTOMER CONTEXT ERROR", response)
        return response
    show("VERIFIED CUSTOMER CONTEXT", customer_context)

    final, final_latency = compose_final_response(
        question, ml, intervention, routing, retrieval, customer_context
    )
    final["stage_latencies_seconds"] = {
        "ml": ml_latency,
        "security_and_intervention": security_latency,
        "knowledge_routing": routing_latency,
        "rag_retrieval_and_reranking": retrieval.get("latency_seconds", 0.0),
        "tool_calling": final.get("tool_call_latency_seconds", 0.0),
        "final_response": max(0.0, final_latency - final.get("tool_call_latency_seconds", 0.0)),
    }
    final["total_latency_seconds"] = round(time.perf_counter()-total_started, 4)
    # Persist a compact, staff-only diagnostic snapshot alongside the assistant turn.
    # Customer-visible message text remains unchanged.
    final["technical_diagnostics"] = {
        "ml_assessment": ml,
        "security_assessment": security,
        "intervention_assessment": intervention,
        "knowledge_routing": routing,
        "retrieval": {
            "status": retrieval.get("status"),
            "evidence": retrieval.get("evidence", []),
            "latency_seconds": retrieval.get("latency_seconds", 0.0),
        },
        "models": {
            "ml_model": ACTIVE_ML_MODEL,
            "llm_provider": LLM_PROVIDER,
            "llm_model": LLM_MODEL,
            "embedding_model": EMBEDDING_MODEL if RAG_ENABLED else None,
            "reranker_model": RERANKER_MODEL if RAG_ENABLED else None,
            "rag_enabled": RAG_ENABLED,
            "vector_top_k": VECTOR_TOP_K,
            "rerank_top_k": RERANK_TOP_K,
            "max_context_chars": MAX_CONTEXT_CHARS,
        },
        "stage_latencies_seconds": final["stage_latencies_seconds"],
        "total_latency_seconds": final["total_latency_seconds"],
        "tool_diagnostics": final.get("tool_diagnostics", {"calls": [], "latency_seconds": 0.0}),
    }
    if final.get("human_intervention_required"):
        admin = build_admin_packet(question, ml, intervention, security, routing, retrieval,
                                   final.get("human_intervention_reason") or "Final response requires human review.")
        final["status"] = "ESCALATED"
        final["decision"] = "ESCALATE"
        final["admin_evidence"] = admin
    show("FINAL RESPONSE", final)
    return final


def login(db_connection) -> dict | None:
    """Collect and validate the demo customer's ID."""
    print("\nCustomer Support | Customer Login")
    print("Enter your customer ID.")
    while True:
        try:
            customer_id_input = input("Customer ID: ").strip()
            if customer_id_input.lower() in {"exit", "quit"}:
                return None
        except (EOFError, KeyboardInterrupt):
            return None

        result = validate_login(customer_id_input, "", db_connection)
        if result["ok"]:
            print(f"\n[SUCCESS] {result['message']} Welcome, "
                  f"{result['customer']['first_name']} {result['customer']['last_name']}.")
            return result
        print(f"\n[LOGIN ERROR] {result['message']} Please try again.\n")


def choose_order(customer_id: int, db_connection) -> str | None:
    """Show the five latest owned orders; blank means no order selected."""
    orders = get_recent_customer_orders(customer_id, 5, db_connection)
    print("\nYour 5 most recent orders:")
    if not orders:
        print("No orders found. You can still ask general support questions.")
        return None
    for index, order in enumerate(orders, 1):
        products = ", ".join(
            item.get("product_name", "Item") for item in order.get("items", [])
        ) or "Item"
        print(f"{index}. {order['order_id']} | {products} | {order.get('order_status', 'unknown')}")
    print("0. No order / general support")
    while True:
        choice = input("Select one order (0-5, or press Enter to skip): ").strip()
        if not choice or choice == "0":
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(orders):
            return orders[int(choice) - 1]["order_id"]
        print("Please enter one of the displayed numbers, or 0 to continue without an order.")


def _is_yes(text: str) -> bool:
    return text.strip().casefold() in {"yes", "y", "yeah", "yep", "resolved", "haan", "ha", "जी हाँ"}


def _is_no(text: str) -> bool:
    return text.strip().casefold() in {"no", "n", "nope", "not yet", "not resolved", "nahi", "नहीं"}


def _assistant_message(response: dict) -> str:
    return str(response.get("message") or
               ("Your request has been sent to our support team for review."
                if response.get("status") == "ESCALATED"
                else "I couldn't complete that request safely. Please try again or contact support."))


def _persist_response(conversation_id: str, response: dict) -> None:
    message = _assistant_message(response)
    diagnostics = response.get("technical_diagnostics") or response.get("admin_evidence")
    if isinstance(diagnostics, dict):
        diagnostics = dict(diagnostics)
        diagnostics.setdefault("models", {
            "ml_model": ACTIVE_ML_MODEL,
            "llm_provider": LLM_PROVIDER,
            "llm_model": LLM_MODEL,
            "embedding_model": EMBEDDING_MODEL if RAG_ENABLED else None,
            "reranker_model": RERANKER_MODEL if RAG_ENABLED else None,
            "rag_enabled": RAG_ENABLED,
            "vector_top_k": VECTOR_TOP_K,
            "rerank_top_k": RERANK_TOP_K,
            "max_context_chars": MAX_CONTEXT_CHARS,
        })
    append_message(conversation_id, "assistant", message, {
        "status": response.get("status"),
        "decision": response.get("decision"),
        "citations": response.get("citations", []),
        "technical_diagnostics": diagnostics,
    })


def _handle_customer_turn(question: str, session: dict, conversation: dict,
                          db_connection) -> tuple[dict | None, bool]:
    """Persist and process one CLI turn. Returns (response, conversation_ended)."""
    conversation_id = conversation["conversation_id"]
    state = conversation.get("state") or {}
    current = get_conversation(conversation_id, session["customer_id"])
    if not current or current["status"] in {"closed", "resolved"}:
        print("[INFO] This support conversation is no longer active.")
        return None, True

    saved_user_message = append_message(conversation_id, "customer", question)
    if not saved_user_message.get("ok"):
        print("[INFO] This conversation has expired or is no longer active. Please start a new support chat.")
        return None, True

    # A human-review ticket remains active. Preserve the session and append
    # customer follow-up messages without re-running the automated pipeline.
    if current["status"] == "under_review":
        response = {
            "status": "ESCALATED", "decision": "ESCALATE",
            "message": (
                f"Your ticket {current.get('ticket_number')} is still under review. "
                "I've added your message to the conversation for the support team."
            ),
            "ticket_number": current.get("ticket_number"),
            "human_intervention_required": True, "citations": [],
        }
        _persist_response(conversation_id, response)
        print(response["message"])
        return response, False

    # Resolve the previous order-clarification turn deterministically.
    if state.get("kind") == "pending_order_clarification":
        match = re.search(r"\bORD-[A-Z0-9-]+\b", question, re.IGNORECASE)
        if not match:
            response = {"status": "NEEDS_CLARIFICATION",
                        "message": "Please reply with one of the order IDs listed above."}
            _persist_response(conversation_id, response)
            print(response["message"])
            return response, False
        order_id = match.group(0).upper()
        selected = select_order(conversation_id, session["customer_id"], order_id)
        if not selected.get("ok"):
            response = {"status": "NEEDS_CLARIFICATION",
                        "message": "That order ID isn't in your account. Please choose one of the listed orders."}
            _persist_response(conversation_id, response)
            print(response["message"])
            return response, False
        original_question = state.get("original_question") or "Please help me with my order."
        response = answer_question(original_question, session["customer_id"], order_id, db_connection)
    elif state.get("kind") == "awaiting_resolution_confirmation":
        if _is_yes(question):
            response = {
                "status": "RESOLVED",
                "message": "Thank you for confirming. Your support conversation is now closed.",
            }

            # Save the final assistant message BEFORE changing the conversation status.
            saved = append_message(
                conversation_id,
                "assistant",
                response["message"],
            )

            if not saved.get("ok"):
                response = {
                    "status": "ERROR",
                    "message": "I couldn't save the conversation confirmation. Please try again.",
                }
                print(response["message"])
                return response, False

            result = close_conversation(
                conversation_id,
                "resolved_by_customer",
                "Customer confirmed the issue was resolved.",
                resolved=True,
            )

            if not result.get("ok"):
                response = {
                    "status": "ERROR",
                    "message": "Your confirmation was saved, but the conversation could not be closed. Please contact support.",
                }
                print(response["message"])
                return response, False

            print(response["message"])
            return response, True
            
        if _is_no(question):
            update_state(conversation_id, {}, status="open")
            response = {"status": "CONTINUE",
                        "message": "Thanks for letting me know. Tell me what is still not resolved, and I'll continue helping."}
            append_message(conversation_id, "assistant", response["message"])
            print(response["message"])
            return response, False
        response = {"status": "NEEDS_CLARIFICATION",
                    "message": "Please reply yes if the issue is resolved, or no if you still need help."}
        _persist_response(conversation_id, response)
        print(response["message"])
        return response, False
    else:
        response = answer_question(question, session["customer_id"],
                                   conversation.get("order_id"), db_connection)

    status = response.get("status")
    consistency_warnings = response.get("data_consistency_warnings") or []
    question_lower = question.casefold()
    order_specific_question = bool(re.search(r"\bORD-[A-Z0-9-]+\b", question, re.IGNORECASE)) or any(
        term in question_lower for term in (
            "where is my order", "track my order", "payment status",
            "payment for", "when will", "delivery status", "shipment status",
        )
    )
    consistency_requires_review = bool(consistency_warnings) and order_specific_question
    requires_human_review = (
        status == "ESCALATED"
        or bool(response.get("human_intervention_required"))
        or consistency_requires_review
    )


    if requires_human_review:
        admin = response.get("admin_evidence") or {}

        # Data consistency warnings must take precedence over a generic
        # intervention reason from an earlier pipeline stage.
        if consistency_warnings:
            warning = consistency_warnings[0]

            reason = (
                f"Order data inconsistency requires human verification: "
                f"order {warning.get('order_id', 'unknown')}; "
                f"payment status={warning.get('payment_status', 'unknown')}; "
                f"order status={warning.get('order_status', 'unknown')}; "
                f"shipment status={warning.get('shipment_status', 'unknown')}."
            )

            if warning.get("payment_status") in {"failed", "pending"}:
                assigned_team = "Payment Operations"
                category = "payment_verification"
            else:
                assigned_team = "Customer Support"
                category = "order_status"

            priority = "high"

        else:
            reason = (
                admin.get("reason")
                or response.get("human_intervention_reason")
                or "The AI workflow requires human support."
            )
            assigned_team = admin.get("queue") or "Customer Support"
            category = "general"
            priority = "medium"

        latest = get_conversation(
            conversation_id, session["customer_id"]
        ) or {}

        recent_turns = latest.get("conversation", [])[-8:]

        transcript = "\n".join(
            f"{item.get('role', 'unknown')}: "
            f"{str(item.get('message', ''))[:500]}"
            for item in recent_turns
        )

        summary = f"{reason}\nRecent conversation:\n{transcript}"

        escalated = escalate_conversation(
            conversation_id,
            reason,
            summary,
            category=category,
            priority=priority,
            assigned_team=assigned_team,
        )

        if escalated.get("ok"):
            response["status"] = "ESCALATED"
            response["decision"] = "ESCALATE"
            response["human_intervention_required"] = True
            response["human_intervention_reason"] = reason
            response["ticket_number"] = escalated["ticket_number"]

            response["message"] = (
                "Your request has been forwarded to our support team. "
                f"Your ticket number is {escalated['ticket_number']}. "
                "Our team will review it and contact you."
            )

            _persist_response(conversation_id, response)
            print(response["message"])
            return response, False



    

    if status == "REFUSED" and response.get("security_termination"):
        _persist_response(conversation_id, response)
        close_conversation(conversation_id, "security_termination",
                           "Conversation terminated by the security policy.")
        print(_assistant_message(response))
        return response, True

    _persist_response(conversation_id, response)
    if status == "NEEDS_CLARIFICATION" and "Which one are you asking about?" in _assistant_message(response):
        update_state(conversation_id, {
            "kind": "pending_order_clarification",
            "original_question": question,
        }, status="awaiting_customer")
    elif status == "ANSWERED":
        # Keep the conversation open without forcing a typed yes/no after each reply.
        update_state(conversation_id, {"kind": "answer_provided"},
                     status="awaiting_customer")
        response["resolution_confirmation_required"] = True
        _replace_last_assistant_message(conversation_id, _assistant_message(response))
    print(_assistant_message(response))
    return response, False


def _replace_last_assistant_message(conversation_id: str, message: str) -> None:
    """Update the last assistant turn atomically, preserving one JSON row per ticket."""
    from app.ticket_service import replace_last_assistant_message
    replace_last_assistant_message(conversation_id, message)


def _timeout_worker(stop_event: threading.Event) -> None:
    while not stop_event.wait(30):
        try:
            closed = close_inactive_conversations(15)
            if closed:
                print(f"\n[TICKETS] Automatically closed {closed} inactive conversation(s).")
        except Exception as exc:
            print(f"\n[TICKETS] Timeout check failed ({type(exc).__name__}).")


def main() -> None:
    db_connection = None
    timeout_stop = threading.Event()
    timeout_thread = None
    try:
        initialize_support_schema()
        db_connection = start_db()
        health = check_db(db_connection)
        if not health.get("ok"):
            print("[ERROR] Customer database is unavailable. Exiting.")
            return

        session = login(db_connection)
        if session is None:
            print("\nGoodbye.")
            return

        existing = get_active_conversation(session["customer_id"])
        if existing and existing["status"] == "under_review":
            print(f"\nYou already have an open support ticket: {existing['ticket_number']}. "
                  "Please wait for the support team.")
            return
        if existing:
            conversation = existing
            print(f"\n[INFO] Resuming your active support conversation: {conversation['ticket_number']}")
        else:
            order_id = choose_order(session["customer_id"], db_connection)
            created = create_conversation(session["customer_id"], order_id)
            if not created.get("ok"):
                existing = get_active_conversation(session["customer_id"])
                if not existing:
                    print("[ERROR] Could not create a support conversation.")
                    return
                conversation = existing
            else:
                conversation = get_conversation(created["conversation_id"], session["customer_id"])
                print(f"\n[INFO] Support conversation created: {created['ticket_number']}")

        startup()
        print("Type 'exit' to leave. Your conversation will remain open for 15 minutes "
              "after your last activity.\n")
        timeout_thread = threading.Thread(target=_timeout_worker, args=(timeout_stop,), daemon=True)
        timeout_thread.start()

        while True:
            try:
                question = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye. Your conversation remains saved.")
                break
            if question.lower() in {"exit", "quit"}:
                print("Goodbye. Your conversation remains saved.")
                break
            if not question:
                continue
            try:
                response, ended = _handle_customer_turn(
                    question, session, conversation, db_connection
                )
                refreshed = get_conversation(conversation["conversation_id"], session["customer_id"])
                if refreshed:
                    conversation = refreshed
                if ended:
                    break
            except Exception as exc:
                error = {
                    "status": "ERROR",
                    "message": "The request could not be processed safely.",
                    "error_type": type(exc).__name__,
                }
                append_message(conversation["conversation_id"], "assistant", error["message"],
                               {"status": "ERROR"})
                show("APPLICATION ERROR", error)
    except Exception as exc:
        print(f"[FATAL] Unable to start customer session ({type(exc).__name__}).")
    finally:
        timeout_stop.set()
        if timeout_thread and timeout_thread.is_alive():
            timeout_thread.join(timeout=2)
        if db_connection is not None:
            stop_db(db_connection)
            print("[DATABASE] Session connection closed.")


if __name__ == "__main__":
    main()
