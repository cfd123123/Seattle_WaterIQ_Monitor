package com.example.waterbusiness.common;

import io.micrometer.tracing.Tracer;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.MDC;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.UUID;

/**
 * Writes trace id to MDC and response header {@code X-Trace-Id}.
 * <p>Runs <strong>after</strong> Micrometer creates the entry span; prefers OTEL trace id for logs and Tempo;
 * falls back to client header or random UUID when no active span.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 100)
public class TraceIdFilter extends OncePerRequestFilter {

    public static final String MDC_KEY = "traceId";

    private final ObjectProvider<Tracer> tracerProvider;

    public TraceIdFilter(ObjectProvider<Tracer> tracerProvider) {
        this.tracerProvider = tracerProvider;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        String traceId = resolveTraceId(request);
        MDC.put(MDC_KEY, traceId);
        response.setHeader("X-Trace-Id", traceId);
        try {
            filterChain.doFilter(request, response);
        } finally {
            MDC.remove(MDC_KEY);
        }
    }

    private String resolveTraceId(HttpServletRequest request) {
        Tracer tracer = tracerProvider.getIfAvailable();
        if (tracer != null) {
            var span = tracer.currentSpan();
            if (span != null && span.context() != null && StringUtils.hasText(span.context().traceId())) {
                return span.context().traceId();
            }
        }
        String header = request.getHeader("X-Trace-Id");
        if (StringUtils.hasText(header)) {
            return header.trim();
        }
        return UUID.randomUUID().toString();
    }
}
