package com.example.waterbusiness.repository;

import com.example.waterbusiness.entity.AlertEvent;
import jakarta.persistence.criteria.Predicate;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

public final class AlertSpecifications {

    private AlertSpecifications() {
    }

    /**
     * @param status          exact {@code NEW} / {@code ACK} / {@code CLOSED} (trimmed)
     * @param createdFrom     {@code created_at >=} inclusive lower bound
     * @param createdTo       {@code created_at <=} inclusive upper bound
     * @param severity        e.g. {@code MEDIUM} / {@code HIGH} (case-insensitive)
     * @param pollutionLevel  snapshot e.g. {@code Poor} / {@code Very Poor} (case-insensitive, AI text)
     */
    public static Specification<AlertEvent> filtered(
            String status,
            LocalDateTime createdFrom,
            LocalDateTime createdTo,
            String severity,
            String pollutionLevel
    ) {
        return (root, query, cb) -> {
            List<Predicate> predicates = new ArrayList<>();
            if (StringUtils.hasText(status)) {
                predicates.add(cb.equal(root.get("status"), status.trim()));
            }
            if (createdFrom != null) {
                predicates.add(cb.greaterThanOrEqualTo(root.get("createdAt"), createdFrom));
            }
            if (createdTo != null) {
                predicates.add(cb.lessThanOrEqualTo(root.get("createdAt"), createdTo));
            }
            if (StringUtils.hasText(severity)) {
                predicates.add(cb.equal(
                        cb.upper(root.get("severity")),
                        severity.trim().toUpperCase(Locale.ROOT)));
            }
            if (StringUtils.hasText(pollutionLevel)) {
                predicates.add(cb.equal(
                        cb.lower(root.get("pollutionLevel")),
                        pollutionLevel.trim().toLowerCase(Locale.ROOT)));
            }
            if (predicates.isEmpty()) {
                return cb.conjunction();
            }
            return cb.and(predicates.toArray(Predicate[]::new));
        };
    }
}
